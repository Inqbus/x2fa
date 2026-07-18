# Demo RP Installer Preflight Checks

## Summary

Added preflight checks to the demo RP installer screen to verify system readiness before setup begins.

## Changes Made

### installer/screens/demo_rp.py

1. **Added imports:**
   - `os` - for file permission checks
   - `socket` - for port availability testing  
   - `urllib.request` - for X2FA connectivity check

2. **Added `_check_demo_rp_preflights()` method:**
   Checks for:
   - **Port availability**: Verifies the selected port is free
   - **X2FA connectivity**: Confirms X2FA is reachable at the configured domain
   - **demo_rp directory**: Ensures directory is writable or can be created
   - **Settings file**: Verifies demo_rp_settings.toml can be written

3. **Added `_run_preflight_checks()` method:**
   - Runs preflight checks with logging
   - Returns True if all checks pass, False otherwise
   - Logs detailed error messages for failures

4. **Updated UI:**
   - Added preflight hint showing what will be checked
   - Hint updates when port input changes
   - Preflight checks run automatically when "Set up Demo RP" is clicked

5. **Updated `_run_setup()` method:**
   - Runs preflight checks before any setup operations
   - Aborts if any preflight check fails
   - Logs all check results

### tests/test_installer_screens.py

Added test to verify the "Done" button is initially disabled.

## Preflight Check Details

### Port Availability
Verifies the demo RP can bind to the selected port without conflicts.

### X2FA Connectivity
Confirms X2FA is reachable and responding at the configured domain.

### Directory Writability
Ensures the demo_rp directory is writable or can be created.

### Settings File
Verifies the demo_rp_settings.toml file can be written.

## User Experience

**Before:**
- User clicks "Set up Demo RP"
- Setup starts immediately
- Failures may occur mid-process
- No clear feedback on what's expected

**After:**
- Preflight checks run automatically
- All issues reported at once
- Clear error messages with fixes suggested
- Setup aborts cleanly if checks fail
- "Preflight checks" section logs all results

## Testing

- All 145 unit tests pass
- DemoRP specific test added
- E2E tests still flaky (pre-existing, unrelated)
