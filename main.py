from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import subprocess
import tempfile
import os
import re

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Xavfli operatsiyalar ro'yxati
BLACKLISTED_PATTERNS = [
    r"(os|subprocess)\.(system|popen|fork|exec)",
    r"__import__\s*\(",
    r"eval\s*\(",
    r"open\s*\(",
    r"shutil\.",
    r"rm\s+-rf",
    r"docker\.",
    r"\.write\s*\("
]

# Ruxsat berilgan kutubxonalar (whitelist)
ALLOWED_LIBRARIES = {
    'numpy', 'pandas', 'matplotlib', 
    'requests', 'scikit-learn', 'seaborn'
}

def validate_code(code: str):
    """Kodni xavfsizlik tekshiruvidan o'tkazish"""
    for pattern in BLACKLISTED_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            raise HTTPException(400, f"Taqiqlangan operatsiya: {pattern}")

def install_libraries(libraries: str):
    """Kutubxonalarni xavfsiz o'rnatish"""
    libs = [lib.strip() for lib in libraries.split(',')]
    
    # Whitelist tekshiruvi
    for lib in libs:
        if lib.lower() not in ALLOWED_LIBRARIES:
            raise HTTPException(400, f"Taqiqlangan kutubxona: {lib}")
    
    # Pip install
    try:
        result = subprocess.run(
            ["pip", "install"] + libs,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Kutubxona o'rnatish vaqti tugadi")
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
@app.post("/run")
async def run_code(
    code: str = Form(...),
    libraries: str = Form("")
):
    try:
        # 1. Kodni tekshirish
        validate_code(code)
        
        # 2. Kutubxonalarni o'rnatish
        pip_result = ""
        if libraries:
            install_result = install_libraries(libraries)
            pip_result = f"PIP OUTPUT:\n{install_result.stdout}\n"
            if install_result.stderr:
                pip_result += f"PIP ERRORS:\n{install_result.stderr}\n"

        # 3. Vaqtinchalik fayl yaratish
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as tmp:
            tmp.write(code.encode())
            tmp_file_name = tmp.name

        # 4. Kodni ishga tushirish
        result = subprocess.run(
            ["python", tmp_file_name],
            capture_output=True,
            text=True,
            timeout=10,
            env={"PYTHONPATH": "/tmp"}  # Tizim katalogidan izolatsiya
        )
        
        # 5. Tozalash
        os.unlink(tmp_file_name)

        return {
            "output": pip_result + result.stdout,
            "error": result.stderr,
            "status": "success"
        }

    except HTTPException as he:
        return {"error": str(he.detail), "status": "failed"}
    except subprocess.TimeoutExpired:
        return {"error": "Kod 10 soniyadan ko'p vaqt oldi", "status": "failed"}
    except Exception as e:
        return {"error": f"Kutilmagan xatolik: {str(e)}", "status": "failed"}
    finally:
        if 'tmp_file_name' in locals() and os.path.exists(tmp_file_name):
            os.unlink(tmp_file_name)