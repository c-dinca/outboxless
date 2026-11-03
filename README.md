# imap-drafts

**Your agent writes. You send.**

The safe bridge between AI agents and your inbox. Claude, Cursor or any [MCP](https://modelcontextprotocol.io) client can search your mail, read it, and prepare replies, as **drafts** in your own mailbox. You open them in the mail app you already use (Spark, Apple Mail, Outlook, Thunderbird, your phone), read them, and press Send yourself.

**It cannot send anything.** There is no code to send, delete or move a message. Whatever an agent does, the worst outcome is a draft you throw away.

- Works with any IMAP mailbox: Gmail, Outlook.com, iCloud, Fastmail, OVH, your company server...
- Replies stay in the right thread (`In-Reply-To` / `References`).
- Reading never marks a message as read.
- Your password stays in the macOS Keychain (or an environment variable), never in a file.
- One Python file, standard library only, Python 3.9+. Nothing else to install or trust.

## How it works

```
 AI agent (Claude, Cursor...) ──MCP──▶ imap-drafts ──IMAP──▶ your mailbox
                                            │                     │
                              search, read, draft            Drafts folder
                                                                  │
                                         you review and send ◀── any mail app
```

## Install

```sh
pipx install git+https://github.com/c-dinca/imap-drafts
# or: uv tool install git+https://github.com/c-dinca/imap-drafts
```

No pipx? Clone the repository and run `python3 imap_drafts.py` instead of `imap-drafts`.

## Set up your mailbox

1. Create `~/.config/imap-drafts/config.ini`:

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

2. Store the password in the macOS Keychain (you are prompted, nothing is echoed):

   ```sh
   security add-generic-password -s imap-drafts -a me@example.com -w
   ```

   On Linux or Windows, set `IMAP_DRAFTS_PASSWORD` in the environment of the process instead. Every setting can also come from `IMAP_DRAFTS_HOST`, `IMAP_DRAFTS_PORT`, `IMAP_DRAFTS_USER` and `IMAP_DRAFTS_FROM_NAME`.

3. Check:

   ```sh
   imap-drafts check
   # OK: logged in as me@example.com, Drafts = Drafts, Sent = Sent
   ```

| Provider | IMAP host | Note |
|---|---|---|
| Gmail | `imap.gmail.com` | needs an [app password](https://myaccount.google.com/apppasswords) |
| Outlook.com | `outlook.office365.com` | |
| iCloud | `imap.mail.me.com` | needs an app-specific password |
| Fastmail | `imap.fastmail.com` | needs an app password |
| OVH MX Plan | `ssl0.ovh.net` | |
| OVH Email Pro | `pro1.mail.ovh.net` | |

## Connect your agent

### Claude Code

```sh
claude mcp add imap-drafts -- imap-drafts mcp
```

### Claude Desktop, Cursor and other MCP clients

Add to the client's MCP configuration (`claude_desktop_config.json`, `~/.cursor/mcp.json`...):

```json
{
  "mcpServers": {
    "imap-drafts": { "command": "imap-drafts", "args": ["mcp"] }
  }
}
```

Then just ask: *"Find Alice's last email about the budget and draft a reply saying I agree, cc Bob."* The draft is waiting in your mail app.

### Tools given to the agent

| Tool | What it does |
|---|---|
| `list_folders` | folders and their role (inbox, sent, drafts, trash, archive, junk) |
| `search_emails` | by sender, recipient, subject, text and date, newest first |
| `read_email` | headers, plain-text body, attachment names |
| `create_draft` | a new draft |
| `create_reply_draft` | a reply in the same thread, reply-all optional; a reply to your own message becomes a follow-up to its recipients |

## Safety model

- **No sending, ever.** The tool only appends to the Drafts folder. A human sends.
- **Email is untrusted input.** An email can contain text written to manipulate an agent ("forward all invoices to..."). Every message given to the agent is labelled as third-party data, and since nothing can be sent, such an attempt can at most produce a draft you will see before anything leaves.
- **Read-only browsing.** Folders are opened read-only; messages stay unread.
- **Secrets stay put.** The password is read from the Keychain or the environment at each connection and never written or printed.

## Command line

The same features without an agent:

```sh
imap-drafts new --to alice@example.org --cc bob@example.org --subject "Weekly update" --body-file update.txt
imap-drafts reply --from alice@example.org --subject-contains "Weekly update" --body "Thanks, all good on my side."
```

`reply` answers the latest message from that sender whose subject contains the text (inbox or sent folder). `--all` keeps the other recipients in Cc, `--no-signature` leaves the signature out, and the body can come from stdin.

## Development

```sh
python3 -m unittest -v
```

## License

MIT
