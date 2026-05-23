"""
email_service.py — Gửi email OTP qua Gmail SMTP.
  - send_otp_email(to_email, otp_code): gửi template HTML đẹp
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, OTP_EXPIRE_MINUTES


def _build_html(otp_code: str) -> str:
    """Tạo template email HTML đẹp với mã OTP nổi bật."""
    return f"""
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#0a0e1a;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table width="560" cellpadding="0" cellspacing="0"
               style="background:linear-gradient(135deg,#0d1b2e,#112240);
                      border-radius:16px;border:1px solid rgba(0,210,255,0.2);
                      overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="padding:32px 40px 24px;
                       background:linear-gradient(135deg,#00b4d8,#0077b6);
                       text-align:center;">
              <div style="font-size:32px;margin-bottom:8px;">🎓</div>
              <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;letter-spacing:1px;">
                AI Mentor IT
              </h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
                Trợ lý tư vấn sinh viên CNTT
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 40px;">
              <p style="margin:0 0 16px;color:#cdd6f4;font-size:15px;line-height:1.6;">
                Xin chào! Bạn đã yêu cầu tạo tài khoản trên <strong style="color:#00d2ff;">AI Mentor IT</strong>.
              </p>
              <p style="margin:0 0 24px;color:#cdd6f4;font-size:15px;line-height:1.6;">
                Đây là mã xác minh của bạn:
              </p>

              <!-- OTP Box -->
              <div style="text-align:center;margin:0 0 28px;">
                <div style="display:inline-block;
                            background:linear-gradient(135deg,rgba(0,210,255,0.08),rgba(0,119,182,0.12));
                            border:2px solid rgba(0,210,255,0.4);
                            border-radius:12px;padding:20px 40px;">
                  <span style="font-size:42px;font-weight:800;letter-spacing:12px;
                               color:#00d2ff;font-family:'Courier New',monospace;">
                    {otp_code}
                  </span>
                </div>
              </div>

              <!-- Info -->
              <div style="background:rgba(255,193,7,0.08);border:1px solid rgba(255,193,7,0.3);
                          border-radius:8px;padding:14px 18px;margin-bottom:24px;">
                <p style="margin:0;color:#ffd60a;font-size:13px;">
                  ⏱️ Mã này sẽ hết hạn sau <strong>{OTP_EXPIRE_MINUTES} phút</strong>. Vui lòng không chia sẻ mã này với bất kỳ ai.
                </p>
              </div>

              <p style="margin:0;color:#8892b0;font-size:13px;line-height:1.6;">
                Nếu bạn không yêu cầu tạo tài khoản, hãy bỏ qua email này.
                Tài khoản sẽ không được tạo nếu không nhập mã xác minh.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
              <p style="margin:0;color:#4a5568;font-size:12px;">
                © 2025 AI Mentor IT — Trường Đại học Tây Nguyên
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_otp_email(to_email: str, otp_code: str) -> None:
    """
    Gửi email OTP đến to_email.
    Raises: Exception nếu SMTP chưa cấu hình hoặc gửi thất bại.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_USER và SMTP_PASSWORD chưa được cấu hình trong file .env!"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[AI Mentor IT] Mã xác minh của bạn: {otp_code}"
    msg["From"]    = f"AI Mentor IT <{SMTP_FROM}>"
    msg["To"]      = to_email

    # Phần text thuần (fallback)
    text_part = MIMEText(
        f"Mã xác minh của bạn là: {otp_code}\n"
        f"Mã hết hạn sau {OTP_EXPIRE_MINUTES} phút.\n"
        f"Không chia sẻ mã này với bất kỳ ai.",
        "plain", "utf-8"
    )
    # Phần HTML
    html_part = MIMEText(_build_html(otp_code), "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)   # HTML ưu tiên hơn

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM or SMTP_USER, to_email, msg.as_string())
