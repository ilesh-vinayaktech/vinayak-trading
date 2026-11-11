import logging

from algo.portal.mailer import ConsoleMailer


def test_the_console_mailer_remembers_what_it_would_send_and_logs_no_link(caplog):
    m = ConsoleMailer()
    with caplog.at_level(logging.INFO, logger="algo.portal.mail"):
        m.send("jane@example.com", "Hello", "secret link http://x/?token=abc")
    assert [(x.to, x.subject, x.body) for x in m.sent] == [
        ("jane@example.com", "Hello", "secret link http://x/?token=abc")
    ]
    assert "jane@example.com" in caplog.text and "token=abc" not in caplog.text
