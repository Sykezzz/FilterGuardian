import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QWizard, QDialog
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from setup_wizard import SetupWizard, validate_address
import theme
import main

app = QApplication.instance() or QApplication([])


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.saved = {}
        self.targets = []
        self.wizard = self.new_wizard()

    def new_wizard(self):
        wizard = SetupWizard(self.saved, self.targets,
                             lambda cfg: self.saved.update(cfg),
                             lambda targets: self.targets.__setitem__(slice(None), targets))
        wizard.show()
        app.processEvents()
        return wizard

    def tearDown(self):
        self.wizard.deleteLater()
        app.processEvents()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def next(self):
        QTest.mouseClick(self.wizard.button(QWizard.NextButton), Qt.LeftButton)
        app.processEvents()

    def test_clean_install_default_finish_and_back(self):
        self.next()
        self.wizard.name.setText('Morgan')
        self.next()
        self.wizard.target_text.setPlainText('Northstar Sandbox | links, arcade | link-review, resources')
        self.next()
        QTest.mouseClick(self.wizard.button(QWizard.BackButton), Qt.LeftButton)
        self.assertEqual(self.wizard.currentId(), 2)
        self.next()
        self.next()
        self.wizard.confirm.setChecked(True)
        QTest.mouseClick(self.wizard.button(QWizard.FinishButton), Qt.LeftButton)
        self.assertEqual(self.wizard.result(), QDialog.Accepted)
        self.assertEqual(self.saved['user_name'], 'Morgan')
        self.assertFalse(self.saved['browser_monitor_enabled'])
        self.assertFalse(self.saved['on_premises'])
        self.assertEqual(self.saved['filter_test_addr'], '')
        self.assertEqual(self.targets[0]['explicit_channels'], ['link-review', 'resources'])

    def test_cancel_resume_excludes_token(self):
        self.wizard.name.setText('Morgan')
        self.wizard.method.setCurrentText('Relay Agent')
        self.wizard.address.setText('http://relay.example:9224')
        self.wizard.token.setText('fictional-private-token')
        self.wizard.reject()
        self.assertEqual(self.saved, {})
        text = Path('setup_draft.json').read_text()
        self.assertNotIn('fictional-private-token', text)
        self.wizard.deleteLater()
        self.wizard = self.new_wizard()
        self.assertEqual(self.wizard.name.text(), 'Morgan')
        self.assertEqual(self.wizard.address.text(), 'http://relay.example:9224')
        self.assertEqual(self.wizard.token.text(), '')
        self.assertEqual(self.wizard.currentId(), 0)

    def test_relay_validation_and_final_save(self):
        self.wizard.method.setCurrentText('Relay Agent')
        self.wizard.address.setText('http://relay.example:9224')
        self.assertIn('authorized', self.wizard.validate_network())
        self.wizard.permission.setChecked(True)
        self.assertIn('token', self.wizard.validate_network())
        self.wizard.token.setText('fictional-token')
        self.assertEqual(self.wizard.validate_network(), '')
        self.wizard.confirm.setChecked(True)
        self.wizard.accept()
        self.assertEqual(self.saved['filter_test_token'], 'fictional-token')

    def test_invalid_targets_and_name_block_save(self):
        self.wizard.name.setText('')
        self.wizard.confirm.setChecked(True)
        self.wizard.accept()
        self.assertEqual(self.saved, {})
        self.wizard.name.setText('Morgan')
        self.wizard.target_text.setPlainText('Northstar\nnorthstar')
        self.assertIn('only once', self.wizard.validate_targets())
        self.wizard.accept()
        self.assertEqual(self.saved, {})

    def test_reopen_preserves_unrelated_existing_settings(self):
        self.wizard.config['unrelated_preference'] = 'keep'
        self.wizard.confirm.setChecked(True)
        self.wizard.accept()
        self.assertEqual(self.saved['unrelated_preference'], 'keep')
        self.wizard.deleteLater()
        self.wizard = self.new_wizard()
        self.assertEqual(self.wizard.name.text(), self.saved['user_name'])

    def test_setup_makes_no_network_or_system_changes(self):
        with patch('socket.socket', side_effect=AssertionError('No sockets in setup')), \
             patch('subprocess.Popen', side_effect=AssertionError('No subprocess in setup')):
            self.wizard.confirm.setChecked(True)
            self.wizard.accept()
        self.assertTrue(self.saved['setup_complete'])

    def test_address_validation(self):
        for value in ['relay.example', 'file:///example', 'http://host:99999',
                      'http://user:secret@host', 'http://host/path', 'http://host?token=x', 'http://bad host']:
            self.assertFalse(validate_address(value), value)
        for value in ['http://relay.example:9224', 'https://proxy.example', 'http://127.0.0.1:9224']:
            self.assertTrue(validate_address(value), value)

    def test_real_local_persistence_and_first_run_schedule(self):
        self.wizard.save_config = main.save_config
        self.wizard.save_targets = main.save_targets
        self.wizard.target_text.setPlainText('Northstar Sandbox | links | link-review')
        self.wizard.confirm.setChecked(True)
        self.wizard.accept()
        self.assertTrue(main.load_config()['setup_complete'])
        self.assertEqual(main.load_targets()[0]['name'], 'Northstar Sandbox')
        Path('app_config.json').unlink()
        setup_calls = []
        with patch.object(main.MainWindow, 'open_setup', new=lambda self: setup_calls.append(True)):
            window = main.MainWindow()
            app.processEvents()
            self.assertEqual(setup_calls, [True])
            for page in range(6):
                window._goto(page)
            window._quit()

    def test_keyboard_focus_moves_between_fields(self):
        self.next()
        self.wizard.name.setFocus()
        QTest.keyClick(self.wizard.name, Qt.Key_Tab)
        self.assertIsNot(self.wizard.focusWidget(), self.wizard.name)

    def test_instruction_and_focus_contrast(self):
        def luminance(color):
            rgb = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
            return sum(weight * (v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)
                       for weight, v in zip((.2126,.7152,.0722), rgb))
        for name, tokens in theme.THEMES.items():
            fg, bg = sorted([luminance(tokens['text_primary']), luminance(tokens['bg_surface'])])
            self.assertGreaterEqual((bg+.05)/(fg+.05), 4.5, name)


if __name__ == '__main__':
    unittest.main()
