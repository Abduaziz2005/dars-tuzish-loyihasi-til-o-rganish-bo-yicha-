from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json, os, copy, base64, zlib, hashlib, secrets
from sqlalchemy import or_, and_

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR}/data/langlearn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'langlearn-secret-2024'

# O'qituvchi paroli — SHA-256 hash of '200519992806'
TEACHER_PASS_HASH = hashlib.sha256(b'200519992806').hexdigest()

# .urok fayl magic bytes
UROK_MAGIC   = b'UROKFILE'
UROK_VERSION = 2

# ─── Shifrlash yordamchilari ──────────────────────────────────────────────────

def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def encode_urok(payload: dict) -> str:
    """dict → shifrlangan base64 string (.urok fayl ichiga yoziladi)"""
    raw        = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    compressed = zlib.compress(raw, level=9)
    key        = b'LangLearn2024xK9'
    xored      = _xor_bytes(compressed, key)
    final      = UROK_MAGIC + bytes([UROK_VERSION]) + xored
    return base64.b64encode(final).decode('ascii')

def decode_urok(b64_str: str) -> dict:
    """shifrlangan base64 string → dict"""
    try:
        raw = base64.b64decode(b64_str.strip())
    except Exception:
        raise ValueError("Base64 decode xatosi")
    if not raw.startswith(UROK_MAGIC):
        raise ValueError("Noto'g'ri fayl formati (magic bytes mos emas)")
    data       = raw[len(UROK_MAGIC) + 1:]
    key        = b'LangLearn2024xK9'
    compressed = _xor_bytes(data, key)
    jsonbytes  = zlib.decompress(compressed)
    return json.loads(jsonbytes.decode('utf-8'))

# ─── Models ───────────────────────────────────────────────────────────

db = SQLAlchemy(app)

class User(db.Model):
    """Talaba / O'qituvchi"""
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    email      = db.Column(db.String(200), unique=True, nullable=False)
    role       = db.Column(db.String(20), default='student')  # 'student' yoki 'teacher'
    is_blocked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True, cascade='all, delete-orphan')
    groups = db.relationship('Group', secondary='group_members', backref='members')
    created_groups = db.relationship('Group', backref='created_by_user', foreign_keys='Group.created_by')

class Group(db.Model):
    """O'quvchilar guruhi"""
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    messages = db.relationship('ChatMessage', backref='group', lazy=True, cascade='all, delete-orphan')

# Association table for group members
group_members = db.Table('group_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class ChatMessage(db.Model):
    """Chat xabarlari"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text       = db.Column(db.Text, nullable=False)
    
    # Chat turi: 'personal' (1-1), 'group' (guruh), 'global' (hamma)
    chat_type  = db.Column(db.String(20), default='global')  
    
    # Receiver (personal chat uchun)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Group (group chat uchun)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    
    # Blok qilganlar
    blocked_for_users = db.Column(db.Text, default='{}')  # JSON: {user_id: True, ...}
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    receiver = db.relationship('User', foreign_keys=[receiver_id])

class Lesson(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    subtitle   = db.Column(db.String(200), default='')
    order      = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    blocks     = db.relationship('Block', backref='lesson', lazy=True,
                                 cascade='all, delete-orphan',
                                 order_by='Block.order')

class Block(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    lesson_id  = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    type       = db.Column(db.String(50), nullable=False)
    order      = db.Column(db.Integer, default=0)
    data       = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'lesson_id': self.lesson_id,
            'type': self.type,
            'order': self.order,
            'data': json.loads(self.data or '{}'),
        }

class StudentProgress(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    block_id   = db.Column(db.Integer, db.ForeignKey('block.id'), nullable=False)
    answers    = db.Column(db.Text, default='{}')
    score      = db.Column(db.Float, default=0)
    max_score  = db.Column(db.Float, default=100)
    completed  = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StudentResult(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(200), default='O\'quvchi')
    lesson_title = db.Column(db.String(200), default='')
    total_score  = db.Column(db.Float, default=0)
    max_score    = db.Column(db.Float, default=0)
    answers_json = db.Column(db.Text, default='{}')
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Init DB ──────────────────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
    with app.app_context():
        db.create_all()
        if Lesson.query.count() == 0:
            seed_demo()

def seed_demo():
    # Dars 1: СТУДЕНТ!
    lesson1 = Lesson(title='Дарс 1: СТУДЕНТ!', subtitle='A1', order=1)
    db.session.add(lesson1)
    db.session.flush()

    blocks_data_1 = [
        (0, 'heading', {'text': 'СТУДЕНТ! Salomlashish va Tanishish', 'level': 1, 'color': '#e63946', 'bg': ''}),
        (1, 'hr', {'color': '#e63946'}),
        (2, 'listening', {
            'title': '👂 Tinglash Mashqlari: Salomlashish',
            'questions': [
                {
                    'audio': '',
                    'question': '1. Odamning ismi kimdir?',
                    'options': ['Anton', 'Natasha', 'Petr', 'Elena'],
                    'correct': 1
                }
            ]
        }),
        (3, 'vocab', {
            'title': 'Янги сўзлар (Новые слова)', 'bar_color': '#457b9d',
            'items': [
                {'ru': 'Привет!', 'uz': 'Salom!', 'audio': ''},
                {'ru': 'Добрый день!', 'uz': 'Xayrli kun!', 'audio': ''},
            ]
        }),
    ]
    
    for order, btype, bdata in blocks_data_1:
        b = Block(lesson_id=lesson1.id, type=btype, order=order,
                  data=json.dumps(bdata, ensure_ascii=False))
        db.session.add(b)
    
    db.session.commit()

# ─── API: User Registration/Login ──────────────────────────────────────

@app.route('/api/user/register', methods=['POST'])
def register_user():
    """Yangi foydalanuvchi ro'yxatdan o'tish"""
    d = request.json or {}
    name = d.get('name', 'Noma\'lum')
    email = d.get('email', f'user_{secrets.token_hex(4)}@example.com')
    role = d.get('role', 'student')  # 'student' yoki 'teacher'
    password = d.get('password', '')
    
    # O'qituvchi bo'lish uchun parol tekshirish
    if role == 'teacher':
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if pwd_hash != TEACHER_PASS_HASH:
            return jsonify({'ok': False, 'error': 'O\'qituvchi paroli noto\'g\'ri'}), 401
    
    # Mavjud foydalanuvchi tekshirish
    if User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': 'Email allaqachon ro\'yxatdan o\'tgan'}), 400
    
    user = User(name=name, email=email, role=role)
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    session['role'] = role
    
    return jsonify({
        'ok': True,
        'user_id': user.id,
        'name': user.name,
        'role': user.role
    })

@app.route('/api/user/login', methods=['POST'])
def login_user():
    """Foydalanuvchi kirish"""
    d = request.json or {}
    email = d.get('email', '')
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'error': 'Foydalanuvchi topilmadi'}), 404
    
    if user.is_blocked:
        return jsonify({'ok': False, 'error': 'Bu foydalanuvchi blok qilingan'}), 403
    
    session['user_id'] = user.id
    session['role'] = user.role
    
    return jsonify({
        'ok': True,
        'user_id': user.id,
        'name': user.name,
        'role': user.role
    })

@app.route('/api/user/me', methods=['GET'])
def get_current_user():
    """Hozirgi foydalanuvchi ma'lumotlari"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'ok': False, 'error': 'Foydalanuvchi topilmadi'}), 404
    
    return jsonify({
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'is_blocked': user.is_blocked
    })

# ─── API: Groups ──────────────────────────────────────────────────────

@app.route('/api/groups', methods=['GET'])
def get_groups():
    """Barcha guruhlar"""
    groups = Group.query.all()
    return jsonify([{
        'id': g.id,
        'name': g.name,
        'description': g.description,
        'created_by': g.created_by,
        'member_count': len(g.members),
        'created_at': g.created_at.strftime('%Y-%m-%d %H:%M')
    } for g in groups])

@app.route('/api/groups', methods=['POST'])
def create_group():
    """Yangi guruh tashkil etish (faqat o'qituvchi)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Faqat o\'qituvchi guruh tashkil eta oladi'}), 403
    
    d = request.json or {}
    name = d.get('name', 'Yangi guruh')
    description = d.get('description', '')
    
    group = Group(name=name, description=description, created_by=user_id)
    db.session.add(group)
    db.session.commit()
    
    return jsonify({
        'ok': True,
        'id': group.id,
        'name': group.name,
        'created_at': group.created_at.strftime('%Y-%m-%d %H:%M')
    })

@app.route('/api/groups/<int:gid>/add-members', methods=['POST'])
def add_group_members(gid):
    """Guruhga o'quvchilarni qo'shish (faqat o'qituvchi)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    group = Group.query.get_or_404(gid)
    if group.created_by != user_id:
        return jsonify({'ok': False, 'error': 'Faqat guruh yaratuvchi o\'quvchilar qo\'sha oladi'}), 403
    
    d = request.json or {}
    student_ids = d.get('student_ids', [])
    
    for sid in student_ids:
        student = User.query.get(sid)
        if student and student.role == 'student' and student not in group.members:
            group.members.append(student)
    
    db.session.commit()
    
    return jsonify({
        'ok': True,
        'member_count': len(group.members)
    })

@app.route('/api/groups/<int:gid>/members', methods=['GET'])
def get_group_members(gid):
    """Guruh a'zolari"""
    group = Group.query.get_or_404(gid)
    return jsonify([{
        'id': m.id,
        'name': m.name,
        'email': m.email,
        'role': m.role
    } for m in group.members])

# ─── API: Chat System ──────────────────────────────────────────────────────

@app.route('/api/chat/messages', methods=['GET'])
def get_chat_messages():
    """Chat xabarlarini olish"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    chat_type = request.args.get('chat_type', 'global')  # 'global', 'group', 'personal'
    group_id = request.args.get('group_id', None)
    receiver_id = request.args.get('receiver_id', None)
    limit = int(request.args.get('limit', 100))
    
    query = ChatMessage.query
    
    if chat_type == 'global':
        # Hamma uchun chat
        query = query.filter_by(chat_type='global')
    elif chat_type == 'group' and group_id:
        # Guruh chati
        query = query.filter_by(chat_type='group', group_id=int(group_id))
    elif chat_type == 'personal' and receiver_id:
        # Personal 1-1 chat
        query = query.filter_by(chat_type='personal').filter(
            or_(
                and_(ChatMessage.user_id == user_id, ChatMessage.receiver_id == int(receiver_id)),
                and_(ChatMessage.user_id == int(receiver_id), ChatMessage.receiver_id == user_id)
            )
        )
    
    messages = query.order_by(ChatMessage.created_at.desc()).limit(limit).all()
    messages.reverse()  # Qadimagi xabarlar birinchi
    
    result = []
    for msg in messages:
        # Blok qilganlarni tekshirish
        blocked_data = json.loads(msg.blocked_for_users or '{}')
        if str(user_id) in blocked_data:
            continue  # Bu xabar bu foydalanuvchi uchun blok qilingan
        
        result.append({
            'id': msg.id,
            'user_id': msg.user_id,
            'user_name': msg.user.name if msg.user else 'Noma\'lum',
            'text': msg.text,
            'chat_type': msg.chat_type,
            'group_id': msg.group_id,
            'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    return jsonify(result)

@app.route('/api/chat/send', methods=['POST'])
def send_message():
    """Xabar yuborish"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if user.is_blocked:
        return jsonify({'ok': False, 'error': 'Siz blok qilingansiz'}), 403
    
    d = request.json or {}
    text = d.get('text', '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'Xabar boʻsh bolishi mumkin emas'}), 400
    
    chat_type = d.get('chat_type', 'global')  # 'global', 'group', 'personal'
    group_id = d.get('group_id', None)
    receiver_id = d.get('receiver_id', None)
    
    msg = ChatMessage(
        user_id=user_id,
        text=text,
        chat_type=chat_type,
        group_id=group_id,
        receiver_id=receiver_id
    )
    db.session.add(msg)
    db.session.commit()
    
    return jsonify({
        'ok': True,
        'id': msg.id,
        'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/chat/block/<int:msg_id>', methods=['POST'])
def block_message(msg_id):
    """Xabarni o'zingiz uchun yashirish"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    msg = ChatMessage.query.get_or_404(msg_id)
    
    blocked_data = json.loads(msg.blocked_for_users or '{}')
    blocked_data[str(user_id)] = True
    
    msg.blocked_for_users = json.dumps(blocked_data)
    db.session.commit()
    
    return jsonify({'ok': True})

@app.route('/api/chat/delete/<int:msg_id>', methods=['DELETE'])
def delete_message(msg_id):
    """Xabarni o'chirish (faqat xabar yozuvchi yoki o'qituvchi)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    msg = ChatMessage.query.get_or_404(msg_id)
    user = User.query.get(user_id)
    
    # Faqat xabar yozuvchi yoki o'qituvchi o'chira oladi
    if msg.user_id != user_id and user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    db.session.delete(msg)
    db.session.commit()
    
    return jsonify({'ok': True})

@app.route('/api/chat/user-block/<int:blocked_user_id>', methods=['POST'])
def block_user(blocked_user_id):
    """Foydalanuvchini blok qilish (faqat o'qituvchi)"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Faqat o\'qituvchi foydalanuvchilarni blok qila oladi'}), 403
    
    blocked_user = User.query.get_or_404(blocked_user_id)
    blocked_user.is_blocked = True
    db.session.commit()
    
    return jsonify({'ok': True, 'message': f'{blocked_user.name} blok qilingan'})

@app.route('/api/chat/users', methods=['GET'])
def get_all_users():
    """Barcha foydalanuvchilar"""
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'name': u.name,
        'email': u.email,
        'role': u.role,
        'is_blocked': u.is_blocked
    } for u in users])

# ─── API: Lessons ────────────────────────────────────────────────────────

@app.route('/api/lessons', methods=['GET'])
def get_lessons():
    lessons = Lesson.query.order_by(Lesson.order).all()
    return jsonify([{
        'id': l.id, 'title': l.title, 'subtitle': l.subtitle,
        'order': l.order, 'block_count': len(l.blocks)
    } for l in lessons])

@app.route('/api/lessons/<int:lid>/blocks', methods=['GET'])
def get_blocks(lid):
    blocks = Block.query.filter_by(lesson_id=lid).order_by(Block.order).all()
    return jsonify([b.to_dict() for b in blocks])

# ─── API: Progress ────────────────────────────────────────────────────────

@app.route('/api/progress/dashboard', methods=['GET'])
def get_progress_dashboard():
    """Progress dashboard"""
    lessons = Lesson.query.order_by(Lesson.order).all()
    dashboard = []
    
    for lesson in lessons:
        blocks = Block.query.filter_by(lesson_id=lesson.id).all()
        total_score = 0
        max_score = 0
        completed = 0
        
        for block in blocks:
            prog = StudentProgress.query.filter_by(block_id=block.id).first()
            if prog:
                total_score += prog.score
                max_score += prog.max_score
                if prog.completed:
                    completed += 1
        
        dashboard.append({
            'lesson_id': lesson.id,
            'title': lesson.title,
            'subtitle': lesson.subtitle,
            'total_blocks': len(blocks),
            'completed_blocks': completed,
            'score': total_score,
            'max_score': max_score,
            'percentage': round(total_score / max_score * 100) if max_score > 0 else 0
        })
    
    return jsonify(dashboard)

# ─── Upload ──────────────────────────────────────────────────────────

@app.route('/api/upload/audio', methods=['POST'])
def upload_audio():
    f = request.files.get('file')
    if not f: return jsonify({'error': 'no file'}), 400
    audio_dir = os.path.join(BASE_DIR, 'static', 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    fname = f'{datetime.utcnow().timestamp()}_{f.filename}'
    f.save(os.path.join(audio_dir, fname))
    return jsonify({'url': f'/static/audio/{fname}'})

# ─── Pages ──────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)

if __name__ == '__main__':
    init_db()
    print('\n🚀  LangLearn ishga tushdi!  →  http://127.0.0.1:5000\n')
    app.run(debug=True, port=5000)
