"""Offline workflow verification: test doubles only; no browser or sockets."""
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import MagicMock, patch

import analyzer
import browser_monitor
import database
import relay_agent


class SyntheticWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        database.init_db()
        analyzer._session_asked.clear()

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def rows(self):
        with closing(sqlite3.connect('proxies.db')) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute('SELECT * FROM blacklisted_urls')]

    def test_capture_deduplicates_full_url_without_inventing_root(self):
        page = MagicMock()
        page.evaluate.return_value = ['See https://arcade.example/play', 'https://arcade.example/play']
        with patch.object(browser_monitor, 'log_debug'):
            monitor = browser_monitor.BrowserMonitor()
        events = []
        self.assertTrue(monitor._harvest_page(page, set(), 'Northstar/link-review', events.append))
        self.assertEqual([r['url'] for r in self.rows()], ['https://arcade.example/play'])
        self.assertEqual(events, ['https://arcade.example/play'])

    def test_capture_bare_domain_and_whitelist(self):
        page = MagicMock()
        page.evaluate.return_value = ['resource.example google.com']
        with patch.object(browser_monitor, 'log_debug'):
            monitor = browser_monitor.BrowserMonitor()
        monitor._harvest_page(page, set(), 'Northstar/link-review', lambda _: None)
        self.assertEqual([r['url'] for r in self.rows()], ['https://resource.example'])

    def visit(self, known=False, filtered=False):
        url = 'https://arcade.example/play'
        database.add_url(url, 'Demo', 'Northstar/link-review')
        page = MagicMock()
        page.url = url
        page.title.return_value = 'Cover Page'
        page.content.return_value = ('<title>Access denied</title> Network Filter' if filtered else
                                   '<meta property="og:site_name" content="Orbit Arcade"> play arcade games')
        page.eval_on_selector_all.return_value = ['https://arcade.example/uv/uv.bundle.js']
        page.evaluate.return_value = '<body><main></main></body>'
        page.frames = []
        page.screenshot.return_value = b'synthetic-preview'
        response = MagicMock()
        response.headers = {'server': 'Netlify'}
        page.goto.return_value = response
        pw = MagicMock()
        browser = pw.chromium.launch.return_value
        browser.new_context.return_value.new_page.return_value = page
        manager = MagicMock()
        manager.__enter__.return_value = pw
        if known:
            analyzer.save_known_site(analyzer.fingerprint(page), 'Confirmed Orbit Arcade')
        with patch('playwright.sync_api.sync_playwright', return_value=manager), \
             patch.object(analyzer, '_is_on_premises', return_value=filtered), \
             patch.object(analyzer, '_safe_print'):
            analyzer._visit(1, url)
        browser.close.assert_called_once()
        return self.rows()[0]

    def test_brain_persists_detected_identity_and_review_queue(self):
        row = self.visit()
        self.assertEqual((row['status'], row['site_name'], row['proxy_tech'], row['platform']),
                         ('analyzed', 'Orbit Arcade', 'Ultraviolet', 'Netlify'))
        self.assertEqual(row['category'], 'Gaming / Arcade')
        pending = json.loads(Path('pending_fingerprints.json').read_text())
        self.assertEqual(len(pending), 1)
        self.assertEqual(next(iter(pending.values()))['site_name'], 'Orbit Arcade')

    def test_confirmed_fingerprint_overrides_cover_metadata(self):
        row = self.visit(known=True)
        self.assertEqual(row['site_name'], 'Confirmed Orbit Arcade')
        self.assertFalse(Path('pending_fingerprints.json').exists())

    def test_on_premises_block_is_filtered_not_analyzed(self):
        row = self.visit(filtered=True)
        self.assertEqual((row['status'], row['site_name']), ('filtered', 'Network Filter'))

    def test_brain_retry_then_success(self):
        with patch.object(analyzer, '_visit', side_effect=[RuntimeError('connection reset'), None]) as visit, \
             patch.object(analyzer.time, 'sleep'), patch.object(analyzer, '_safe_print'):
            analyzer.analyze_site(1, 'https://arcade.example')
        self.assertEqual(visit.call_count, 2)

    def relay_request(self, path, token='', resolves=True, available=False):
        handler = object.__new__(relay_agent._RelayHandler)
        handler.path = path
        handler._json = MagicMock()
        with patch.object(relay_agent, '_TOKEN', token), \
             patch.object(relay_agent, '_host_resolves', return_value=resolves), \
             patch.object(relay_agent, '_PW_AVAILABLE', available), \
             patch.object(relay_agent, '_fetch_urllib', return_value={'result':'allowed','detail':'Synthetic'}) as fetch, \
             patch.object(relay_agent, '_fetch_playwright', return_value={'result':'blocked','detail':'Synthetic'}) as browser:
            handler.do_GET()
        return handler._json.call_args, fetch.call_count, browser.call_count

    def test_relay_authorization_and_scheme(self):
        call, fetch, browser = self.relay_request('/test?url=https://arcade.example', token='synthetic')
        self.assertEqual(call.args[1], 403)
        self.assertEqual(fetch + browser, 0)
        call, fetch, browser = self.relay_request('/test?url=file:///example')
        self.assertEqual(call.args[0]['detail'], 'Invalid URL scheme')
        self.assertEqual(fetch + browser, 0)

    def test_relay_dead_domain_skips_fetch(self):
        call, fetch, browser = self.relay_request('/test?url=https://retired.example', resolves=False)
        self.assertEqual(call.args[0]['result'], 'dead')
        self.assertEqual(fetch + browser, 0)

    def test_relay_dispatches_urllib_and_playwright(self):
        call, fetch, browser = self.relay_request('/test?url=https://arcade.example')
        self.assertEqual((call.args[0]['result'], fetch, browser), ('allowed', 1, 0))
        call, fetch, browser = self.relay_request('/test?url=https://arcade.example', available=True)
        self.assertEqual((call.args[0]['result'], fetch, browser), ('blocked', 0, 1))

    def test_relay_browser_fetch_settles_navigation_and_closes_resources(self):
        page = MagicMock()
        page.url = 'https://arcade.example'
        page.title.return_value = 'Orbit Arcade'
        page.content.side_effect = [RuntimeError('page is navigating and changing the content'),
                                    '<title>Orbit Arcade</title>']
        page.goto.return_value.status = 200
        manager = MagicMock()
        browser = manager.__enter__.return_value.chromium.launch.return_value
        context = browser.new_context.return_value
        context.new_page.return_value = page
        with patch.object(relay_agent, '_sync_playwright', return_value=manager):
            result = relay_agent._fetch_playwright(page.url, 'http://proxy.example:8080')
        self.assertEqual(result['result'], 'allowed')
        page.wait_for_load_state.assert_called_once()
        self.assertEqual(context.new_page.call_count, 1)
        self.assertEqual(browser.new_context.call_args.kwargs['proxy'],
                         {'server': 'http://proxy.example:8080'})
        page.close.assert_called_once()
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_relay_urllib_block_page(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://arcade.example'
        response.read.return_value = b'<title>Access denied</title>'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(relay_agent.urllib.request, 'build_opener', return_value=opener):
            result = relay_agent._fetch_urllib('https://arcade.example', '')
        self.assertEqual(result['result'], 'blocked')


if __name__ == '__main__':
    unittest.main()
