# Changelog

## 0.1.0 — 2026-10-26

First release: the full capture → split → collect → auto-settle loop on a laptop.

### Added
- Money helpers in integer paise with Indian number formatting (#2)
- Nine-table SQLite data model with backup (#3)
- Split engine: equal, exact, percentage, shares, adjustment (#4)
- Net balances and greedy debt simplification (#5)
- UPI links, QR codes and WhatsApp summary (#6)
- Five-stage SMS pipeline (#7) and plugins for 11 banks and UPI apps (#8)
- Importers for SMS Backup & Restore XML, bank statements and WhatsApp chats (#9)
- Auto-settle from credit SMS (#10)
- `hisaab anonymize` (#11) and optional local Ollama fallback (#12)
- Import, groups, insights and export services (#13–#15)
- Gradio app with six tabs (#16), CLI and demo mode (#17)

### Fixed
- The owner could not store their own UPI ID, so no QR codes appeared (#18)
- Backups leaked a SQLite connection (#19)
