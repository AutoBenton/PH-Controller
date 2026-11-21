"""mailer.py -- Email sending service for exporting session CSV data via SMTP (e.g. Gmail)."""

import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import smtplib
import ssl
import config as cfg_mod


def _connect_and_login(server_host: str, port: int, user: str, pw: str, timeout: int = 20):
    """Attempt SMTP connection and login with automatic fallback between ports 587 and 465."""
    clean_user = user.strip()
    clean_pw = pw.strip().replace(" ", "")

    ports_to_try = [port]
    if port == 587 and 465 not in ports_to_try:
        ports_to_try.append(465)
    elif port == 465 and 587 not in ports_to_try:
        ports_to_try.append(587)

    last_exc = None
    for p in ports_to_try:
        server = None
        try:
            ctx = ssl.create_default_context()
            if p == 465:
                server = smtplib.SMTP_SSL(server_host, p, context=ctx, timeout=timeout)
            else:
                server = smtplib.SMTP(server_host, p, timeout=timeout)
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()

            server.login(clean_user, clean_pw)
            return server, p
        except smtplib.SMTPAuthenticationError:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass
            raise
        except Exception as exc:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass
            last_exc = exc

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Could not connect to {server_host} on ports {ports_to_try}")


def test_smtp_connection(
    email_user=None,
    email_password=None,
    smtp_server=None,
    smtp_port=None,
    cfg=None,
) -> dict:
    """Test SMTP credentials by connecting and authenticating."""
    if cfg is None:
        cfg = cfg_mod.load()

    user = (email_user if email_user is not None else cfg.get("email_user", "")).strip()
    pw = (
        email_password
        if email_password is not None
        else cfg.get("email_password", "")
    )
    server_host = (
        (smtp_server if smtp_server is not None else cfg.get("smtp_server", "smtp.gmail.com"))
        .strip()
    ) or "smtp.gmail.com"
    try:
        port = int(
            smtp_port if smtp_port is not None else cfg.get("smtp_port", 465)
        )
    except (ValueError, TypeError):
        port = 465

    if not user:
        return {"ok": False, "error": "Sender email address cannot be empty."}
    if not pw:
        return {"ok": False, "error": "Sender email password cannot be empty."}

    server = None
    try:
        server, used_port = _connect_and_login(server_host, port, user, pw, timeout=15)
        return {
            "ok": True,
            "message": f"Successfully authenticated with {server_host} (port {used_port}) as {user}.",
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "ok": False,
            "error": (
                "SMTP Authentication failed. For Gmail accounts, please use a Google App Password "
                "(Google Account -> Security -> 2-Step Verification -> App Passwords) "
                "rather than your standard Gmail account password."
            ),
        }
    except smtplib.SMTPConnectError as exc:
        return {
            "ok": False,
            "error": f"Failed to connect to SMTP server ({server_host}:{port}): {exc}",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Connection error: {exc}"}
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


def send_session_email(
    recipient: str,
    session_filenames: list,
    sessions_dir: str,
    cfg: dict = None,
) -> dict:
    """Send one or more session CSV files as attachments to the specified recipient."""
    if cfg is None:
        cfg = cfg_mod.load()

    user = (cfg.get("email_user") or "").strip()
    pw = cfg.get("email_password") or ""
    server_host = (cfg.get("smtp_server") or "smtp.gmail.com").strip()
    try:
        port = int(cfg.get("smtp_port") or 465)
    except (ValueError, TypeError):
        port = 465

    if not user or not pw:
        return {
            "ok": False,
            "error": (
                "Email credentials are not configured. Please set your email "
                "and password under Settings."
            ),
        }

    recipient = (recipient or "").strip()
    if not recipient or "@" not in recipient or "." not in recipient:
        return {"ok": False, "error": f"Invalid recipient email address: '{recipient}'"}

    if not session_filenames:
        return {"ok": False, "error": "No session files were selected for export."}

    valid_attachments = []
    missing_files = []
    for fn in session_filenames:
        clean_fn = os.path.basename(str(fn).strip())
        if not clean_fn.endswith(".csv"):
            continue
        path = os.path.join(os.path.abspath(sessions_dir), clean_fn)
        if os.path.isfile(path):
            valid_attachments.append((clean_fn, path))
        else:
            missing_files.append(clean_fn)

    if not valid_attachments:
        return {
            "ok": False,
            "error": f"Selected session files were not found on disk: {', '.join(missing_files) if missing_files else 'None'}",
        }

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = recipient
    n_files = len(valid_attachments)
    file_word = "session" if n_files == 1 else "sessions"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg["Subject"] = f"pH Controller Export - {n_files} {file_word} ({now_str})"

    file_list_text = "\n".join(
        f"  - {name} ({round(os.path.getsize(p) / 1024, 1)} KB)"
        for name, p in valid_attachments
    )
    body = (
        f"Hello,\n\n"
        f"Exported session data from the pH Controller is attached.\n\n"
        f"Date: {now_str}\n"
        f"Sessions ({n_files}):\n{file_list_text}\n\n"
        f"--\npH Controller Automated Export"
    )
    msg.attach(MIMEText(body, "plain"))

    for clean_fn, path in valid_attachments:
        try:
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", f'attachment; filename="{clean_fn}"'
            )
            msg.attach(part)
        except Exception as exc:
            return {"ok": False, "error": f"Error reading file '{clean_fn}': {exc}"}

    server = None
    try:
        server, used_port = _connect_and_login(server_host, port, user, pw, timeout=25)
        server.sendmail(user, [recipient], msg.as_string())
        return {
            "ok": True,
            "message": f"Successfully sent {n_files} {file_word} to {recipient}.",
            "files": [name for name, _ in valid_attachments],
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "ok": False,
            "error": (
                "SMTP Authentication failed. For Gmail accounts, please use a Google App Password "
                "(Google Account -> Security -> 2-Step Verification -> App Passwords) "
                "rather than your standard Gmail account password."
            ),
        }
    except smtplib.SMTPConnectError as exc:
        return {
            "ok": False,
            "error": f"Failed to connect to SMTP server ({server_host}:{port}): {exc}",
        }
    except Exception as exc:
        return {"ok": False, "error": f"Failed to send email: {exc}"}
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass
