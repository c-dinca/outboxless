import email
import email.policy
import unittest

import io
import json

from outboxless import (
    MCP_TOOLS,
    DraftsError,
    build_draft,
    decode_mailbox,
    handle_mcp,
    html_to_text,
    imap_quote,
    reply_recipients,
    reply_subject,
    serve_mcp,
)


def parse(raw):
    return email.message_from_string(raw, policy=email.policy.default)


class DecodeMailboxTest(unittest.TestCase):
    def test_modified_utf7(self):
        self.assertEqual(decode_mailbox("&AMk-l&AOk-ments envoy&AOk-s"), "Éléments envoyés")
        self.assertEqual(decode_mailbox("Drafts"), "Drafts")
        self.assertEqual(decode_mailbox("R&-D"), "R&D")


class ReplySubjectTest(unittest.TestCase):
    def test_adds_prefix(self):
        self.assertEqual(reply_subject("Hello"), "RE: Hello")

    def test_keeps_existing_prefix(self):
        self.assertEqual(reply_subject("Re: Hello"), "Re: Hello")
        self.assertEqual(reply_subject("AW: Hallo"), "AW: Hallo")


class BuildDraftTest(unittest.TestCase):
    def test_plain_utf8_message(self):
        message = build_draft("Me <me@example.com>", ["you@example.org"], "Café", "Ça va ?", now=0)
        parsed = email.message_from_bytes(message.as_bytes(), policy=email.policy.default)
        self.assertEqual(parsed["Subject"], "Café")
        self.assertEqual(parsed.get_content().strip(), "Ça va ?")
        self.assertTrue(parsed["Message-ID"].endswith("@example.com>"))
        self.assertIsNone(parsed["In-Reply-To"])

    def test_threading_headers(self):
        message = build_draft(
            "me@example.com", ["you@example.org"], "RE: x", "ok", in_reply_to="<b@x>", references="<a@x>"
        )
        self.assertEqual(message["In-Reply-To"], "<b@x>")
        self.assertEqual(message["References"], "<a@x> <b@x>")

    def test_signature_and_cc(self):
        message = build_draft("me@example.com", ["a@x.org"], "s", "body", cc=["b@x.org"], signature="-- \nMe")
        self.assertEqual(message["Cc"], "b@x.org")
        self.assertIn("body\n\n-- \nMe", message.get_content())

    def test_attachment(self):
        import os, tempfile
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as handle:
            handle.write(b"\x89PNG fake")
        try:
            message = build_draft("me@example.com", ["a@x.org"], "s", "body", attachments=[handle.name])
            [part] = list(message.iter_attachments())
            self.assertEqual(part.get_content_type(), "image/png")
            self.assertEqual(part.get_filename(), os.path.basename(handle.name))
            self.assertIn("body", message.get_body(("plain",)).get_content())
        finally:
            os.unlink(handle.name)

    def test_needs_a_recipient(self):
        with self.assertRaises(DraftsError):
            build_draft("me@example.com", [], "s", "body")


class ReplyRecipientsTest(unittest.TestCase):
    original = parse("From: Alice <alice@x.org>\nTo: me@example.com, Bob <bob@x.org>\nCc: carol@x.org\nSubject: hi\n\nhi")

    def test_reply_goes_to_sender(self):
        self.assertEqual(reply_recipients(self.original, "me@example.com"), (["Alice <alice@x.org>"], []))

    def test_reply_all_keeps_others_in_cc(self):
        to, cc = reply_recipients(self.original, "ME@example.com", reply_all=True)
        self.assertEqual(to, ["Alice <alice@x.org>"])
        self.assertEqual(cc, ["Bob <bob@x.org>", "carol@x.org"])

    def test_reply_to_header_wins(self):
        original = parse("From: a@x.org\nReply-To: list@x.org\nTo: me@example.com\n\nhi")
        self.assertEqual(reply_recipients(original, "me@example.com")[0], ["list@x.org"])

    def test_follow_up_on_my_own_message(self):
        original = parse("From: me@example.com\nTo: alice@x.org\n\nhi")
        self.assertEqual(reply_recipients(original, "me@example.com")[0], ["alice@x.org"])


class HelpersTest(unittest.TestCase):
    def test_html_to_text(self):
        self.assertEqual(html_to_text("<p>Hello&nbsp;<b>you</b></p><style>x{}</style><br>bye"), "Hello you\n\nbye")

    def test_imap_quote(self):
        self.assertEqual(imap_quote('a"b'), '"a\\"b"')
        with self.assertRaises(DraftsError):
            imap_quote("café")


class McpTest(unittest.TestCase):
    config = {"user": "me@example.com"}

    def test_initialize_echoes_a_known_version(self):
        response = handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}, self.config)
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_unknown_version_gets_the_latest(self):
        response = handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999"}}, self.config)
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_tools_never_send(self):
        names = {tool["name"] for tool in MCP_TOOLS}
        self.assertEqual(names, {"list_folders", "search_emails", "read_email", "create_draft", "create_reply_draft"})
        self.assertFalse(any("send" in name or "delete" in name for name in names))

    def test_notification_has_no_answer(self):
        self.assertIsNone(handle_mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.config))

    def test_unknown_method(self):
        response = handle_mcp({"jsonrpc": "2.0", "id": 7, "method": "resources/list"}, self.config)
        self.assertEqual(response["error"]["code"], -32601)

    def test_stdio_lines(self):
        stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\nnot json\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        stdout = io.StringIO()
        serve_mcp(self.config, stdin, stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertEqual(lines[1]["error"]["code"], -32700)
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
