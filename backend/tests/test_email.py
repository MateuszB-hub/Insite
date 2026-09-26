"""SMTP transport selection and delivery failure handling."""

import pytest

from app.auth import email


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.tls_upgraded = False
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.tls_upgraded = True

    def login(self, user, password):
        self.user = user

    def send_message(self, message):
        self.sent.append(message)


class FakeSMTPSSL(FakeSMTP):
    implicit_tls = True


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(email, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(email, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email, "SMTP_USER", "resend")
    monkeypatch.setattr(email, "SMTP_STARTTLS", True)
    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email.smtplib, "SMTP_SSL", FakeSMTPSSL)
    return monkeypatch


def test_port_587_upgrades_with_starttls(smtp):
    smtp.setattr(email, "SMTP_PORT", 587)
    email.send_email("a@example.com", "s", "b")
    server = FakeSMTP.instances[-1]
    assert type(server) is FakeSMTP and server.tls_upgraded
    assert server.sent[0]["To"] == "a@example.com"


def test_port_465_uses_implicit_tls_without_starttls(smtp):
    smtp.setattr(email, "SMTP_PORT", 465)
    email.send_email("a@example.com", "s", "b")
    server = FakeSMTP.instances[-1]
    assert type(server) is FakeSMTPSSL and not server.tls_upgraded


def test_failure_hides_provider_detail(smtp):
    class Boom(FakeSMTP):
        def send_message(self, message):
            raise RuntimeError("550 a@example.com rejected, password=hunter2")

    smtp.setattr(email, "SMTP_PORT", 587)
    smtp.setattr(email.smtplib, "SMTP", Boom)
    with pytest.raises(email.EmailError) as info:
        email.send_email("a@example.com", "s", "b")
    assert "hunter2" not in str(info.value)
    assert "a@example.com" not in str(info.value)
