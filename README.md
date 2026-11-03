# imap-drafts

Put ready-to-send email drafts straight into your mailbox's **Drafts** folder, over IMAP.

The drafts appear in every mail client connected to the account (Spark, Apple Mail, Thunderbird, Outlook, your phone...). You open them there, read them, and press **Send** yourself.

**It cannot send anything.** There is no SMTP code in it, on purpose: a person always has the last word. That makes it a safe tool to give to a script or an AI assistant that writes emails for you.

- One file, Python 3.9+ standard library only, no dependencies.
- Replies land in the right thread (`In-Reply-To` / `References` headers), found by sender and subject.
- The password stays in the macOS Keychain (or an environment variable), never in a file.

## Install

```sh
git clone https://github.com/<you>/imap-drafts.git
cd imap-drafts
python3 imap_drafts.py --version
```

Optionally put it on your PATH: `ln -s "$PWD/imap_drafts.py" /usr/local/bin/imap-drafts`.

## Configure

`~/.config/imap-drafts/config.ini`:

```ini
[account]
host = imap.example.com
port = 993
user = me@example.com
from_name = My Name
; optional
keychain_service = imap-drafts
signature_file = ~/.config/imap-drafts/signature.txt
```

Store the password in the macOS Keychain (you are prompted for it, nothing is echoed):

```sh
security add-generic-password -s imap-drafts -a me@example.com -w
```

On other systems, set `IMAP_DRAFTS_PASSWORD` in the environment instead. Every setting can also come from `IMAP_DRAFTS_HOST`, `IMAP_DRAFTS_PORT`, `IMAP_DRAFTS_USER` and `IMAP_DRAFTS_FROM_NAME`.

Check the setup:

```sh
imap-drafts check
# OK: logged in as me@example.com, Drafts = Drafts, Sent = Sent
```

Common servers: Gmail `imap.gmail.com` (needs an app password), Outlook.com `outlook.office365.com`, OVH MX Plan `ssl0.ovh.net`, iCloud `imap.mail.me.com`, Fastmail `imap.fastmail.com`.

## Use

A new draft:

```sh
imap-drafts new --to alice@example.org --cc bob@example.org --subject "Weekly update" --body-file update.txt
```

A reply in an existing thread (the latest message from that sender whose subject contains the text, in the inbox or in the sent folder):

```sh
imap-drafts reply --from alice@example.org --subject-contains "Weekly update" --body "Thanks, all good on my side."
```

- `--all` keeps the other recipients in Cc (reply all).
- A reply to your own message (a follow-up when nobody answered) goes to that message's recipients.
- The body can also come from stdin: `cat answer.txt | imap-drafts reply ...`.
- `--no-signature` leaves the configured signature out.

Bodies are plain text (UTF-8).

## Tests

```sh
python3 -m unittest -v
```

## License

MIT
