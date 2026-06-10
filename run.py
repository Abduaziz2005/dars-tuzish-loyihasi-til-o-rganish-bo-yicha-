#!/usr/bin/env python3
"""
LangLearn Studio - ishga tushirish skripti
Ishlatish: python run.py
"""
import os, sys, subprocess, time, webbrowser, threading

def check_deps():
    try:
        import flask, flask_sqlalchemy
    except ImportError:
        print("📦 Kerakli kutubxonalar o'rnatilmoqda...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install',
                               'flask', 'flask-sqlalchemy', '--break-system-packages', '-q'])

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    check_deps()
    # change to script dir
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs('data', exist_ok=True)
    os.makedirs('static/audio', exist_ok=True)
    os.makedirs('static/img', exist_ok=True)

    print("""
╔══════════════════════════════════════════╗
║        🌟 LangLearn Studio               ║
║   Til o'rgatish platformasi              ║
╠══════════════════════════════════════════╣
║  URL: http://127.0.0.1:5000              ║
║  To'xtatish: Ctrl+C                      ║
╚══════════════════════════════════════════╝
""")
    threading.Thread(target=open_browser, daemon=True).start()
    from app import app, init_db
    init_db()
    app.run(debug=False, port=5000, host='0.0.0.0')
