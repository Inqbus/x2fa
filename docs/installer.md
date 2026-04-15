● Proposal: X2FA Installer TUI                                                                                                                                                                                                                
                                                                                                                                                                                                                                              
  Scope                                                                                                                                                                                                                                       
                                                                                                                                                                                                                                              
  A guided wizard that takes a fresh checkout to a running, production-ready X2FA instance. Target user: sysadmin who understands OIDC but has never touched X2FA before.                                                                     
                                                                                                                                                                                                                                              
  ---                                                                                                                                                                                                                                         
  Technology                                                                                                                                                                                                                                  
                                                                                                                                                                                                                                              
  Textual — the obvious choice. Already in the Python ecosystem, no native deps, installable via uv. Gives you real forms, progress bars, confirmation dialogs, and a consistent look without a full curses implementation.                   
                                                                                                                                                                                                                                              
  Alternative if you want zero extra deps: a plain click-based wizard with rich for formatting (both are already pulled in transitively). Less polished but works over SSH without color issues.                                              
                                          
  Recommendation: Textual for anything interactive; fall back to --non-interactive flag that reads from a YAML/TOML answer file for automation (CI/Ansible).                                                                                  
                                                                                                                                                                                                                                              
  ---                                                                                                                                                                                                                                         
  Phases / Screens                                                                                                                                                                                                                            
                                                            
  Screen 1 — Preflight                                                                                                                                                                                                                        
    ✓ Python ≥ 3.11                                         
    ✓ uv available                            
    ✓ Port 5000 free                      
    ⚠ Redis not reachable  ← warn, don't block
                                                                                                                                                                                                                                              
  Screen 2 — Database                     
    ○ SQLite (default, zero-config)                                                                                                                                                                                                           
    ○ PostgreSQL  → connection string input + test button                                                                                                                                                                                     
    ○ MySQL       → connection string input + test button
                                                                                                                                                                                                                                              
  Screen 3 — Domain & TLS                                                                                                                                                                                                                     
    Domain: [x2fa.example.com        ]                                                                                                                                                                                                        
    Reverse proxy:                                                                                                                                                                                                                            
    ○ Caddy (auto-HTTPS, recommended)                                                                                                                                                                                                         
    ○ nginx   → shows config snippet to copy                
    ○ Other   → manual                                                                                                                                                                                                                        
                                              
  Screen 4 — Security                                                                                                                                                                                                                         
    Generates SECRET_KEY + SECRET_SALT automatically        
    (shown for review, never stored in plaintext elsewhere)                                                                                                                                                                                   
    Rate limiting storage:                                  
    ○ memory:// (single worker, dev)                                                                                                                                                                                                          
    ○ Redis URI: [redis://localhost:6379/0]                 
                                                                                                                                                                                                                                              
  Screen 5 — CA Setup                                                                                                                                                                                                                         
    ○ Generate new self-signed CA  (recommended)                                                                                                                                                                                              
        CN: [Internal X2FA CA        ]                                                                                                                                                                                                        
        Validity: [3650] days                               
        Output: [/etc/x2fa/ca_key.pem] (mode 0600)                                                                                                                                                                                            
    ○ Import existing CA cert                                                                                                                                                                                                                 
                                                                                                                                                                                                                                              
  Screen 6 — First OIDC Client                                                                                                                                                                                                                
    Client ID:    [shop.example.com           ]                                                                                                                                                                                               
    Redirect URI: [https://shop.example.com/callback]       
    Auth method:                                                                                                                                                                                                                              
    ○ tls_client_auth  (issues cert immediately)            
    ○ private_key_jwt  → JWKS URI: [                ]                                                                                                                                                                                         
                                              
  Screen 7 — Execute                                                                                                                                                                                                                          
    Progress log (each step with ✓/✗):                      
    [ ] Write config files                                                                                                                                                                                                                    
    [ ] flask init-db                                                                                                                                                                                                                         
    [ ] flask init-keys                                                                                                                                                                                                                       
    [ ] flask add-ca                                                                                                                                                                                                                          
    [ ] flask add-client                                                                                                                                                                                                                      
    [ ] Issue client certificate (if tls_client_auth)
    [ ] Write systemd unit file (optional)                                                                                                                                                                                                    
                                                            
  Screen 8 — Summary                      
    ┌─────────────────────────────────────────┐                                                                                                                                                                                               
    │  X2FA is ready                          │                                                                                                                                                                                               
    │                                         │                                                                                                                                                                                               
    │  Start:  gunicorn x2fa.wsgi:app         │                                                                                                                                                                                               
    │          --bind 127.0.0.1:5000          │             
    │                                         │                                                                                                                                                                                               
    │  Client cert:  ./shop.example.com.cert  │
    │  Client key:   ./shop.example.com.key   │                                                                                                                                                                                               
    │  CA cert:      /etc/x2fa/ca_cert.pem    │                                                                                                                                                                                               
    │                                         │
    │  Next: configure your reverse proxy     │                                                                                                                                                                                               
    │  (nginx snippet copied to clipboard)    │                                                                                                                                                                                               
    └─────────────────────────────────────────┘                                                                                                                                                                                               
                                                                                                                                                                                                                                              
  ---                                                                                                                                                                                                                                         
  File layout                                                                                                                                                                                                                                 
                                              
  x2fa/                                                                                                                                                                                                                                       
  └── installer/                                            
      ├── __main__.py          # entry point: python -m installer                                                                                                                                                                             
      ├── app.py               # Textual App, screen routing
      ├── screens/                                                                                                                                                                                                                            
      │   ├── preflight.py                                  
      │   ├── database.py                                                                                                                                                                                                                     
      │   ├── domain.py                   
      │   ├── security.py                                                                                                                                                                                                                     
      │   ├── ca_setup.py                                                                                                                                                                                                                     
      │   ├── client.py
      │   ├── execute.py                                                                                                                                                                                                                      
      │   └── summary.py                                    
      ├── runner.py            # subprocess calls to flask CLI + openssl
      ├── config_writer.py     # writes *.toml files
      └── answers.py           # dataclass holding all collected answers                                                                                                                                                                      
                                              
  The installer is a separate uv run target and has no runtime dependency on the main app's Flask code — it only calls flask as a subprocess. This keeps it clean and testable.                                                               
                                                            
  ---                                                                                                                                                                                                                                         
  What it does NOT do                                                                                                                                                                                                                         
                                                                                                                                                                                                                                              
  - No reverse proxy configuration (too many variants — it generates a snippet and shows it)                                                                                                                                                  
  - No firewall rules                                       
  - No systemctl start (generates unit file, user must enable)
  - No database schema migrations (only init-db on fresh install)
                                                                                                                                                                                                                                              
