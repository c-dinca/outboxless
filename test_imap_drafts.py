import email
import email.policy
import unittest

from imap_drafts import DraftsError, build_draft, decode_mailbox, reply_recipients, reply_subject


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


if __name__ == "__main__":
    unittest.main()
