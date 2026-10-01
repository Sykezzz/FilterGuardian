"""Local first-run setup. Saving settings never starts external connections."""
import json
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QTextEdit)
import theme

DRAFT = Path('setup_draft.json')


def validate_address(value):
    """Require explicit HTTP(S) host and reject credentials/query/path mistakes."""
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
        host = parsed.hostname or ''
        try:
            ipaddress.ip_address(host)
            valid_host = True
        except ValueError:
            valid_host = (len(host) <= 253 and bool(host) and all(
                re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                for label in host.rstrip('.').split('.')))
        return (parsed.scheme in ('http', 'https') and bool(parsed.hostname)
                and valid_host
                and not parsed.username and not parsed.password
                and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
                and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


class ValidatedPage(QWizardPage):
    def __init__(self, title, validate=None):
        super().__init__()
        self.setTitle(title)
        self.validate = validate
        self.body = QVBoxLayout(self)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setAccessibleName('Setup validation message')
        self.body.addWidget(self.error)

    def validatePage(self):
        message = self.validate() if self.validate else ''
        self.error.setText(message)
        return not message


class SetupWizard(QWizard):
    def __init__(self, config, targets, save_config, save_targets, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.targets = list(targets)
        self.save_config = save_config
        self.save_targets = save_targets
        self.setWindowTitle('Set up FilterGuardian')
        self.setMinimumSize(640, 550)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage)
        self.setButtonText(QWizard.FinishButton, 'Save setup')
        # Use the existing theme's strongest text role for readable instructions.
        t = theme._t()
        palette = self.palette()
        for role, color in ((QPalette.Window, t['bg_surface']), (QPalette.WindowText, t['text_primary']),
                            (QPalette.Base, t['bg_card']), (QPalette.Text, t['text_primary']),
                            (QPalette.Button, t['bg_card']), (QPalette.ButtonText, t['text_primary'])):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet(f'QWizard, QWizardPage {{background:{t["bg_surface"]};}} '
                          f'QLabel, QCheckBox {{color:{t["text_primary"]};}} '
                          f'QPushButton:focus {{border:2px solid {t["text_primary"]};}}')

        intro = ValidatedPage('Your own workspace')
        self.note(intro, 'Configure your profile, monitoring targets, and optional filter-test '
                  'connection. Everything you enter stays in local files on this installation. '
                  'No operator settings or browser session are bundled.\n\n'
                  'Setup does not launch Chrome, sign in to Discord, visit URLs, install '
                  'software, change a system proxy, or install certificates. Back edits earlier '
                  'steps. Cancel keeps a local draft; relay tokens must be re-entered.')
        self.addPage(intro)

        profile = ValidatedPage('Profile and browser', self.validate_profile)
        form = QFormLayout()
        self.name = QLineEdit(config.get('user_name', 'Guardian'))
        self.theme = QComboBox()
        self.theme.addItems(list(theme.THEMES))
        self.theme.setCurrentText(config.get('theme', 'midnight'))
        self.browser = QCheckBox('Enable browser monitoring when I click Link to Browser')
        self.browser.setChecked(config.get('browser_monitor_enabled', False))
        form.addRow('Your name', self.name)
        form.addRow('Theme', self.theme)
        form.addRow(self.browser)
        profile.body.addLayout(form)
        self.note(profile, 'Monitoring uses a separate local Chrome profile on port 9223. '
                  'You sign in yourself and select servers you are permitted to monitor. '
                  'Link to Browser asks before launching Chrome. Manual URL entry works without it. '
                  'Start Brain separately visits submitted URLs using Playwright Chromium.')
        self.addPage(profile)

        target = ValidatedPage('Monitoring targets', self.validate_targets)
        self.target_text = QTextEdit()
        self.target_text.setPlaceholderText('Northstar Sandbox | links, arcade | link-review, resources')
        self.target_text.setAccessibleName('Monitoring targets: server, keywords, channels')
        target.body.addWidget(self.target_text)
        self.note(target, 'Optional: one server per line: Server name | comma-separated keywords | '
                  'comma-separated channel names. Leave blank to configure later in Targets. '
                  'Saving does not join servers or read messages.')
        self.addPage(target)

        network = ValidatedPage('Optional network filter tests', self.validate_network)
        form = QFormLayout()
        self.method = QComboBox()
        self.method.addItems(['Configure later', 'Relay Agent', 'HTTP Proxy'])
        if config.get('filter_test_addr'):
            self.method.setCurrentText('HTTP Proxy' if config.get('filter_test_method') == 'proxy' else 'Relay Agent')
        self.address = QLineEdit(config.get('filter_test_addr', ''))
        self.address.setPlaceholderText('http://relay.example:9224')
        self.token = QLineEdit(config.get('filter_test_token', ''))
        self.token.setEchoMode(QLineEdit.Password)
        self.onsite = QCheckBox('This installation is on the filtered network')
        self.onsite.setChecked(config.get('on_premises', False))
        self.permission = QCheckBox('I am authorized to test URLs through this connection')
        form.addRow('Test method', self.method)
        form.addRow('Address', self.address)
        form.addRow('Relay token (local only)', self.token)
        form.addRow(self.onsite)
        form.addRow(self.permission)
        network.body.addLayout(form)
        self.note(network, 'A relay runs on a machine you control in the target network; generate '
                  'its package from Settings and use a token. A proxy address is used only for '
                  'app test requests, not the Windows system proxy. Tokens/settings are local '
                  'plaintext files: keep them private. Current test clients accept inspected '
                  'TLS certificates; verify your environment policy before connecting. '
                  'System proxy and certificate changes require separate explicit consent; '
                  'this wizard provides no such changes.')
        self.method.currentTextChanged.connect(self.update_network)
        self.update_network()
        self.addPage(network)

        review = ValidatedPage('Review and save', self.validate_review)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        review.body.addWidget(self.summary)
        self.confirm = QCheckBox('Save these local settings; start external connections only when I request them')
        review.body.addWidget(self.confirm)
        self.note(review, 'Next steps: install Playwright Chromium with python -m playwright '
                  'install chromium if you want analysis. Open Targets to edit channels. '
                  'Use Link to Browser, Start Brain, or Filter Test only when ready. '
                  'Reopen this menu from Settings at any time.')
        self.addPage(review)
        self.restore_draft()
        self.currentIdChanged.connect(self.page_changed)
        self.page_changed(self.currentId())

    def note(self, page, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        page.body.addWidget(label)

    def update_network(self):
        enabled = self.method.currentText() != 'Configure later'
        self.address.setEnabled(enabled)
        self.token.setEnabled(self.method.currentText() == 'Relay Agent')
        self.permission.setEnabled(enabled)

    def validate_profile(self):
        return '' if 1 <= len(self.name.text().strip()) <= 80 else 'Enter a name between 1 and 80 characters.'

    def parsed_targets(self):
        result = []
        names = set()
        for line in self.target_text.toPlainText().splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) > 3 or not parts[0] or len(parts[0]) > 100:
                raise ValueError('Use Server name | keywords | channels, with a server name up to 100 characters.')
            if parts[0].lower() in names:
                raise ValueError('Each server name must appear only once.')
            names.add(parts[0].lower())
            result.append({'name': parts[0], 'keywords': parts[1] if len(parts) > 1 else '',
                           'explicit_channels': [c.strip().lstrip('#') for c in parts[2].split(',') if c.strip()]
                           if len(parts) > 2 else []})
        return result

    def validate_targets(self):
        try:
            self.parsed_targets()
            return ''
        except ValueError as error:
            return str(error)

    def validate_network(self):
        if self.method.currentText() == 'Configure later':
            return ''
        if not validate_address(self.address.text()):
            return 'Enter http:// or https:// with a host and optional port; no embedded credentials, paths, or query.'
        if not self.permission.isChecked():
            return 'Confirm that you are authorized to use this connection, or choose Configure later.'
        if self.method.currentText() == 'Relay Agent' and not self.token.text().strip():
            return 'Enter a relay token for authenticated access, or choose Configure later.'
        return ''

    def validate_review(self):
        return '' if self.confirm.isChecked() else 'Confirm local settings before saving.'

    def snapshot(self):
        return {'name': self.name.text(), 'theme': self.theme.currentText(),
                'browser': self.browser.isChecked(), 'targets': self.target_text.toPlainText(),
                'method': self.method.currentText(), 'address': self.address.text(),
                'onsite': self.onsite.isChecked(), 'page': max(0, self.currentId())}

    def restore_draft(self):
        self.target_text.setPlainText('\n'.join(f'{t["name"]} | {t.get("keywords", "")} | '
                         + ', '.join(t.get('explicit_channels', [])) for t in self.targets))
        if not DRAFT.exists():
            return
        try:
            draft = json.loads(DRAFT.read_text(encoding='utf-8'))
            self.name.setText(draft.get('name', self.name.text()))
            self.theme.setCurrentText(draft.get('theme', self.theme.currentText()))
            self.browser.setChecked(draft.get('browser', False))
            self.target_text.setPlainText(draft.get('targets', ''))
            self.method.setCurrentText(draft.get('method', 'Configure later'))
            self.address.setText(draft.get('address', ''))
            self.onsite.setChecked(draft.get('onsite', False))
            # Resume saved inputs from the start so Back remains available for every step.
        except (ValueError, TypeError, OSError):
            pass

    def page_changed(self, page):
        if page == 4:
            self.summary.setText(f'Profile: {self.name.text().strip()}\nTheme: {self.theme.currentText()}\n'
                f'Browser monitoring: {"enabled on request" if self.browser.isChecked() else "disabled"}\n'
                f'Targets: {len(self.parsed_targets())}\nFilter tests: {self.method.currentText()}\n'
                f'Address: {self.address.text() if self.method.currentText() != "Configure later" else "none"}\n'
                'Relay token: hidden\nNo connection will be started by saving.')

    def reject(self):
        try:
            DRAFT.write_text(json.dumps(self.snapshot(), indent=2), encoding='utf-8')
        except OSError as error:
            self.currentPage().error.setText(f'Could not save draft: {error}')
            return
        super().reject()

    def accept(self):
        for validate in (self.validate_profile, self.validate_targets, self.validate_network, self.validate_review):
            message = validate()
            if message:
                self.currentPage().error.setText(message)
                return
        config = dict(self.config)
        config.update(user_name=self.name.text().strip(), theme=self.theme.currentText(),
                      browser_monitor_enabled=self.browser.isChecked(),
                      on_premises=self.onsite.isChecked(), setup_complete=True)
        later = self.method.currentText() == 'Configure later'
        config.update(filter_test_method='proxy' if self.method.currentText() == 'HTTP Proxy' else 'relay',
                      filter_test_addr='' if later else self.address.text().strip(),
                      filter_test_token=self.token.text().strip() if self.method.currentText() == 'Relay Agent' else '')
        try:
            self.save_targets(self.parsed_targets())
            self.save_config(config)
            DRAFT.unlink(missing_ok=True)
        except OSError as error:
            self.currentPage().error.setText(f'Could not save setup: {error}. Review local folder permissions and retry.')
            return
        super().accept()
