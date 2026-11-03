#!/usr/bin/env python3
"""imap-drafts: put ready-to-send drafts in your mailbox's Drafts folder over IMAP.

The drafts show up in every mail client connected to the account (Spark, Apple Mail,
Thunderbird, your phone...). You read them there and press Send yourself: this tool
cannot send anything, on purpose.

Standard library only (Python 3.9+).
"""

import argparse
import base64
import configparser
import email
import email.policy
import imaplib
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid, parseaddr

__version__ = "0.1.0"

CONFIG_PATH = os.path.expanduser(os.environ.get("IMAP_DRAFTS_CONFIG", "~/.config/imap-drafts/config.ini"))
DRAFTS_FALLBACKS = ["Drafts", "INBOX.Drafts", "INBOX/Drafts", "Brouillons", "INBOX.Brouillons"]
SENT_FALLBACKS = ["Sent", "INBOX.Sent", "INBOX/Sent", "Sent Messages", "Envoyés", "INBOX.Envoyés"]
REPLY_PREFIX = re.compile(r"^\s*(re|aw|sv|réf|rif)\s*:\s*", re.IGNORECASE)


class DraftsError(Exception):
    pass


# --- configuration ---------------------------------------------------------------------------


def load_config(path=CONFIG_PATH):
    """Account settings from the config file, overridable by environment variables."""
    parser = configparser.ConfigParser()
    parser.read(path)
    account = parser["account"] if parser.has_section("account") else {}
    config = {
        "host": os.environ.get("IMAP_DRAFTS_HOST", account.get("host", "")),
        "port": int(os.environ.get("IMAP_DRAFTS_PORT", account.get("port", "993"))),
        "user": os.environ.get("IMAP_DRAFTS_USER", account.get("user", "")),
        "from_name": os.environ.get("IMAP_DRAFTS_FROM_NAME", account.get("from_name", "")),
        "keychain_service": account.get("keychain_service", "imap-drafts"),
        "signature_file": os.path.expanduser(account.get("signature_file", "")),
    }
    missing = [key for key in ("host", "user") if not config[key]]
    if missing:
        raise DraftsError(f"missing {', '.join(missing)}: set them in {path} (see README) or in IMAP_DRAFTS_* variables")
    return config


def get_password(config):
    """From IMAP_DRAFTS_PASSWORD, else from the macOS Keychain. Never printed."""
    if os.environ.get("IMAP_DRAFTS_PASSWORD"):
        return os.environ["IMAP_DRAFTS_PASSWORD"]
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", config["keychain_service"], "-a", config["user"], "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise DraftsError("no IMAP_DRAFTS_PASSWORD and no macOS Keychain (`security` not found)") from None
    except subprocess.CalledProcessError:
        raise DraftsError(
            f"no password in the Keychain for service '{config['keychain_service']}' and account '{config['user']}'"
            " (see README: security add-generic-password)"
        ) from None
    return result.stdout.rstrip("\n")


# --- building the draft ----------------------------------------------------------------------


def reply_subject(subject):
    """'Hello' -> 'RE: Hello'; an existing RE:/AW:/SV: prefix is kept as is."""
    subject = (subject or "").strip()
    return subject if REPLY_PREFIX.match(subject) else f"RE: {subject}"


def build_draft(
    sender,
    to,
    subject,
    body,
    cc=(),
    bcc=(),
    in_reply_to=None,
    references=None,
    signature=None,
    now=None,
):
    """A plain-text UTF-8 message, ready to be appended to the Drafts folder."""
    if not to:
        raise DraftsError("a draft needs at least one recipient")
    message = EmailMessage(policy=email.policy.SMTP)
    message["From"] = sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    message["Date"] = formatdate(now if now is not None else time.time(), localtime=True)
    domain = parseaddr(sender)[1].rpartition("@")[2] or None
    message["Message-ID"] = make_msgid(domain=domain)
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = " ".join(filter(None, [references, in_reply_to]))
    text = body.rstrip() + "\n"
    if signature:
        text += "\n" + signature.rstrip() + "\n"
    message.set_content(text, charset="utf-8")
    return message


def reply_recipients(original, me, reply_all=False):
    """To and Cc of a reply: the Reply-To (or From) of the original; with reply_all, everyone else in Cc."""
    me = me.lower()
    to = [original.get("Reply-To") or original.get("From")]
    cc = []
    if reply_all:
        others = getaddresses(original.get_all("To", []) + original.get_all("Cc", []))
        to_addresses = {parseaddr(address)[1].lower() for address in to}
        for name, address in others:
            if address and address.lower() != me and address.lower() not in to_addresses:
                cc.append(email.utils.formataddr((name, address)))
                to_addresses.add(address.lower())
    # Replying to a message I sent (a follow-up): write to its recipients instead.
    if parseaddr(to[0])[1].lower() == me:
        to = [address for address in original.get_all("To", [])] or to
    return to, cc


# --- IMAP ------------------------------------------------------------------------------------


def connect(config):
    imap = imaplib.IMAP4_SSL(config["host"], config["port"])
    try:
        imap.login(config["user"], get_password(config))
    except imaplib.IMAP4.error as err:
        raise DraftsError(f"IMAP login refused for {config['user']}: {err}") from None
    return imap


def list_mailboxes(imap):
    """[(flags, name)] for every mailbox."""
    status, lines = imap.list()
    if status != "OK":
        raise DraftsError("cannot list the mailboxes")
    mailboxes = []
    for line in lines:
        text = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', text)
        if match:
            mailboxes.append((match["flags"], match["name"].strip().strip('"')))
    return mailboxes


def find_mailbox(imap, special_use, fallbacks):
    mailboxes = list_mailboxes(imap)
    for flags, name in mailboxes:
        if special_use.lower() in flags.lower():
            return name
    names = {name.lower(): name for _, name in mailboxes}
    for fallback in fallbacks:
        if fallback.lower() in names:
            return names[fallback.lower()]
    raise DraftsError(f"no {special_use} mailbox found among: {', '.join(name for _, name in mailboxes)}")


def decode_mailbox(name):
    """Readable form of a mailbox name sent in IMAP's modified UTF-7 (RFC 3501), e.g. '&AMk-l&AOk-ments' -> 'Éléments'."""

    def decode(match):
        chunk = match.group(1)
        if not chunk:
            return "&"
        chunk = chunk.replace(",", "/")
        return base64.b64decode(chunk + "=" * (-len(chunk) % 4)).decode("utf-16-be")

    return re.sub(r"&([^-]*)-", decode, name)


def quote_mailbox(name):
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def find_original(imap, sender, subject_contains, days, folders):
    """Latest message from `sender` whose subject contains `subject_contains`, in the given folders."""
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    best = None
    needle = (subject_contains or "").lower()
    for folder in folders:
        status, _ = imap.select(quote_mailbox(folder), readonly=True)
        if status != "OK":
            continue
        criteria = ["SINCE", since]
        if sender:
            criteria += ["FROM", f'"{sender}"']
        status, data = imap.uid("SEARCH", None, *criteria)
        if status != "OK" or not data or not data[0]:
            continue
        for uid in reversed(data[0].split()):
            status, parts = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            headers = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            if needle and needle not in str(headers.get("Subject", "")).lower():
                continue
            sent = email.utils.parsedate_to_datetime(headers["Date"]) if headers.get("Date") else None
            if best is None or (sent and best[0] and sent > best[0]):
                best = (sent, headers)
            break  # newest match of this folder
    if best is None:
        raise DraftsError(f"no message from '{sender or 'anyone'}' with '{subject_contains}' in the last {days} days")
    return best[1]


def append_draft(imap, mailbox, message):
    status, data = imap.append(
        quote_mailbox(mailbox), r"(\Draft \Seen)", imaplib.Time2Internaldate(time.time()), message.as_bytes()
    )
    if status != "OK":
        raise DraftsError(f"the server refused the draft: {data}")


# --- command line ----------------------------------------------------------------------------


def read_body(args):
    if args.body is not None:
        return args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as handle:
            return handle.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise DraftsError("no body: use --body, --body-file or pipe it on stdin")


def sender_of(config):
    return email.utils.formataddr((config["from_name"], config["user"])) if config["from_name"] else config["user"]


def signature_of(config, args):
    if args.no_signature or not config["signature_file"] or not os.path.exists(config["signature_file"]):
        return None
    with open(config["signature_file"], encoding="utf-8") as handle:
        return handle.read()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="imap-drafts", description="Put drafts in your IMAP Drafts folder. It never sends anything."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    def body_options(command):
        command.add_argument("--body", help="body text")
        command.add_argument("--body-file", help="file holding the body (UTF-8)")
        command.add_argument("--cc", action="append", default=[], help="Cc address (repeat for several)")
        command.add_argument("--bcc", action="append", default=[], help="Bcc address (repeat for several)")
        command.add_argument("--no-signature", action="store_true", help="leave the configured signature out")

    new = commands.add_parser("new", help="a new draft")
    new.add_argument("--to", action="append", required=True, help="recipient (repeat for several)")
    new.add_argument("--subject", required=True)
    body_options(new)

    reply = commands.add_parser("reply", help="a draft answering the latest matching message, in the same thread")
    reply.add_argument("--from", dest="sender", help="address of the message to answer")
    reply.add_argument("--subject-contains", required=True, help="part of the subject of the message to answer")
    reply.add_argument("--all", action="store_true", help="keep the other recipients in Cc")
    reply.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    reply.add_argument("--subject", help="subject of the reply (default: RE: original subject)")
    body_options(reply)

    commands.add_parser("check", help="log in and show the Drafts and Sent folders")

    args = parser.parse_args(argv)
    try:
        config = load_config()
        imap = connect(config)
        try:
            drafts = find_mailbox(imap, r"\Drafts", DRAFTS_FALLBACKS)
            if args.command == "check":
                sent = find_mailbox(imap, r"\Sent", SENT_FALLBACKS)
                print(f"OK: logged in as {config['user']}, Drafts = {decode_mailbox(drafts)}, Sent = {decode_mailbox(sent)}")
                return 0

            body = read_body(args)
            if args.command == "new":
                message = build_draft(
                    sender_of(config), args.to, args.subject, body, args.cc, args.bcc, signature=signature_of(config, args)
                )
            else:
                folders = ["INBOX", find_mailbox(imap, r"\Sent", SENT_FALLBACKS)]
                original = find_original(imap, args.sender, args.subject_contains, args.days, folders)
                to, cc = reply_recipients(original, config["user"], args.all)
                message = build_draft(
                    sender_of(config),
                    to,
                    args.subject or reply_subject(str(original.get("Subject", ""))),
                    body,
                    cc + args.cc,
                    args.bcc,
                    in_reply_to=original.get("Message-ID"),
                    references=original.get("References"),
                    signature=signature_of(config, args),
                )
            append_draft(imap, drafts, message)
            print(f"Draft saved in {decode_mailbox(drafts)}: \"{message['Subject']}\" to {message['To']}" + (f", cc {message['Cc']}" if message["Cc"] else ""))
            return 0
        finally:
            imap.logout()
    except DraftsError as err:
        print(f"imap-drafts: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
