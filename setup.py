"""Generate installation-specific credentials locally; never ship shared defaults."""
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
path = Path(__file__).parent/'.env'
if path.exists():
    raise SystemExit('.env already exists; preserving the existing installation.')
text = (Path(__file__).parent/'.env.example').read_text()
text = text.replace('GENERATE_ADMIN_TOKEN',secrets.token_urlsafe(48)).replace('GENERATE_ENCRYPTION_KEY',Fernet.generate_key().decode())
path.write_text(text)
path.chmod(0o600)
print('Created .env with new administrator and encryption keys. Add your API key and platform app credentials, then start the service.')
