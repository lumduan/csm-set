# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in csm-set, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

### How to Report

1. Email the maintainers directly (see `pyproject.toml` for contact details)
2. Include a clear description of the vulnerability
3. Include steps to reproduce the issue
4. Include potential impact assessment

### What to Expect

- Acknowledgement within 48 hours
- Status update within 7 days
- Fix timeline communicated once the vulnerability is assessed

### Scope

This project is a research tool that interfaces with TradingView market data. Key security considerations:

- **Credentials**: `TVKIT_AUTH_TOKEN` and browser cookies must never be committed to the repository
- **Data boundary**: Raw OHLCV data must never appear in `results/` exports
- **Public mode**: `CSM_PUBLIC_MODE=true` must prevent all data write/fetch operations

### Out of Scope

- Issues related to TradingView's own platform or API
- Issues requiring physical access to the host machine
