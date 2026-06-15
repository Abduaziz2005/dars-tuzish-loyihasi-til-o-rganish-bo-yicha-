from flask import Flask, render_template, request, jsonify, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json, os, copy, base64, zlib, hashlib, secrets
from sqlalchemy import or_, and_

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR}/data/langlearn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'langlearn-secret-2024'

TEACHER_PASS_HASH = hashlib.sha256(b'200519992806').hexdigest()
UROK_MAGIC   = b'UROKFILE'
UROK_VERSION = 2

def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

def encode_urok(payload: dict) -> str:
    raw        = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    compressed = zlib.compress(raw, level=9)
    key        = b'LangLearn2024xK9'
    xored      = _xor_bytes(compressed, key)
    final      = UROK_MAGIC + bytes([UROK_VERSION]) + xored
    return base64.b64encode(final).decode('ascii')

def decode_urok(b64_str: str) -> dict:
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
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    email      = db.Column(db.String(200), unique=True, nullable=False)
    role       = db.Column(db.String(20), default='student')
    is_blocked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True, cascade='all, delete-orphan')
    groups = db.relationship('Group', secondary='group_members', backref='members')
    created_groups = db.relationship('Group', backref='created_by_user', foreign_keys='Group.created_by')
    announcements = db.relationship('Announcement', backref='created_by_user', foreign_keys='Announcement.created_by')
    attendance = db.relationship('Attendance', backref='user', lazy=True, cascade='all, delete-orphan')
    resources = db.relationship('Resource', backref='uploaded_by_user', foreign_keys='Resource.uploaded_by')
    videos = db.relationship('Video', backref='uploaded_by_user', foreign_keys='Video.uploaded_by')
    video_progress = db.relationship('VideoProgress', backref='user', lazy=True, cascade='all, delete-orphan')
    announcements_read = db.relationship('AnnouncementRead', backref='user', lazy=True, cascade='all, delete-orphan')

group_members = db.Table('group_members',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class Group(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    messages = db.relationship('ChatMessage', backref='group', lazy=True, cascade='all, delete-orphan')
    schedules = db.relationship('Schedule', backref='group', lazy=True, cascade='all, delete-orphan')
    announcements = db.relationship('Announcement', backref='group', lazy=True, cascade='all, delete-orphan')

class ChatMessage(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text       = db.Column(db.Text, nullable=False)
    chat_type  = db.Column(db.String(20), default='global')
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    blocked_for_users = db.Column(db.Text, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    receiver = db.relationship('User', foreign_keys=[receiver_id])

# ─── NEW: Announcement System ────────────────────��─────────────────────

class Announcement(db.Model):
    """O'qituvchining elomlari"""
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    is_pinned  = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    read_by = db.relationship('AnnouncementRead', backref='announcement', lazy=True, cascade='all, delete-orphan')

class AnnouncementRead(db.Model):
    """Talaba elon o'qidi yoki yo'q"""
    id             = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcement.id'), nullable=False)
    user_id        = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    read_at        = db.Column(db.DateTime, default=datetime.utcnow)

# ─── NEW: Schedule & Calendar ──────────────────────────────────────────

class Schedule(db.Model):
    """Dars jadavali, topshiriq muddati, testlar"""
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, default='')
    event_type = db.Column(db.String(50), default='lesson')  # 'lesson', 'assignment', 'test', 'meeting'
    start_time = db.Column(db.DateTime, nullable=False)
    end_time   = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── NEW: Resource Library ──────────────────────────────────────────

class Resource(db.Model):
    """PDF, E-books, va boshqa resurslar"""
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, default='')
    file_url   = db.Column(db.String(500), nullable=False)
    file_type  = db.Column(db.String(50))  # 'pdf', 'doc', 'video', 'audio', 'link'
    file_size  = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── NEW: Attendance Tracking ──────────────────────────────────────────

class Attendance(db.Model):
    """Darsga qatnashish"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    status     = db.Column(db.String(20), default='present')  # 'present', 'absent', 'late', 'excused'
    date       = db.Column(db.Date, nullable=False)
    notes      = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── NEW: Video Hosting & Streaming ────────────────────────────────────

class Video(db.Model):
    """Dars videolari"""
    id         = db.Column(db.Integer, primary_key=True)
    group_id   = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, default='')
    video_url  = db.Column(db.String(500), nullable=False)
    duration   = db.Column(db.Integer, default=0)  # soniyada
    thumbnail  = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    progress = db.relationship('VideoProgress', backref='video', lazy=True, cascade='all, delete-orphan')

class VideoProgress(db.Model):
    """Video ko'rish progres (qaydan ko'rdi)"""
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id   = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    current_time = db.Column(db.Integer, default=0)  # soniyada
    is_completed = db.Column(db.Boolean, default=False)
    watch_time = db.Column(db.Integer, default=0)  # umumiy ko'rish vaqti
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Existing Models ──────────────────────────────────────────────────

class Lesson(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    subtitle   = db.Column(db.String(200), default='')
    order      = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    blocks     = db.relationship('Block', backref='lesson', lazy=True, cascade='all, delete-orphan', order_by='Block.order')

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
    lesson1 = Lesson(title='Дарс 1: СТУДЕНТ!', subtitle='A1', order=1)
    db.session.add(lesson1)
    db.session.flush()
    db.session.commit()

# ─── API: User ────────────────────────────────────────────────────────

@app.route('/api/user/register', methods=['POST'])
def register_user():
    d = request.json or {}
    name = d.get('name', 'Noma\'lum')
    email = d.get('email', f'user_{secrets.token_hex(4)}@example.com')
    role = d.get('role', 'student')
    password = d.get('password', '')
    
    if role == 'teacher':
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if pwd_hash != TEACHER_PASS_HASH:
            return jsonify({'ok': False, 'error': 'O\'qituvchi paroli noto\'g\'ri'}), 401
    
    if User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': 'Email allaqachon ro\'yxatdan o\'tgan'}), 400
    
    user = User(name=name, email=email, role=role)
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    session['role'] = role
    
    return jsonify({'ok': True, 'user_id': user.id, 'name': user.name, 'role': user.role})

@app.route('/api/user/login', methods=['POST'])
def login_user():
    d = request.json or {}
    email = d.get('email', '')
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'ok': False, 'error': 'Foydalanuvchi topilmadi'}), 404
    
    if user.is_blocked:
        return jsonify({'ok': False, 'error': 'Bu foydalanuvchi blok qilingan'}), 403
    
    session['user_id'] = user.id
    session['role'] = user.role
    
    return jsonify({'ok': True, 'user_id': user.id, 'name': user.name, 'role': user.role})

@app.route('/api/user/me', methods=['GET'])
def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'ok': False, 'error': 'Foydalanuvchi topilmadi'}), 404
    
    return jsonify({
        'id': user.id, 'name': user.name, 'email': user.email,
        'role': user.role, 'is_blocked': user.is_blocked
    })

# ─── API: Groups ──────────────────────────────────────────────────────

@app.route('/api/groups', methods=['GET'])
def get_groups():
    groups = Group.query.all()
    return jsonify([{
        'id': g.id, 'name': g.name, 'description': g.description,
        'created_by': g.created_by, 'member_count': len(g.members),
        'created_at': g.created_at.strftime('%Y-%m-%d %H:%M')
    } for g in groups])

@app.route('/api/groups', methods=['POST'])
def create_group():
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
    
    return jsonify({'ok': True, 'id': group.id, 'name': group.name})

@app.route('/api/groups/<int:gid>/add-members', methods=['POST'])
def add_group_members(gid):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    group = Group.query.get_or_404(gid)
    if group.created_by != user_id:
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    d = request.json or {}
    student_ids = d.get('student_ids', [])
    
    for sid in student_ids:
        student = User.query.get(sid)
        if student and student.role == 'student' and student not in group.members:
            group.members.append(student)
    
    db.session.commit()
    return jsonify({'ok': True, 'member_count': len(group.members)})

# ─── API: Announcements ───────────────────────────────────────────────

@app.route('/api/announcements', methods=['POST'])
def create_announcement():
    """O'qituvchi elon beradi"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    user = User.query.get(user_id)
    if user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Faqat o\'qituvchi elon bera oladi'}), 403
    
    d = request.json or {}
    group_id = d.get('group_id')
    title = d.get('title', '')
    content = d.get('content', '')
    
    if not title or not content:
        return jsonify({'ok': False, 'error': 'Sarlavha va mazmun talab'}), 400
    
    announcement = Announcement(
        group_id=group_id,
        created_by=user_id,
        title=title,
        content=content
    )
    db.session.add(announcement)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': announcement.id})

@app.route('/api/announcements/<int:gid>', methods=['GET'])
def get_announcements(gid):
    """Guruh elonlarini olish"""
    announcements = Announcement.query.filter_by(group_id=gid).order_by(
        Announcement.is_pinned.desc(),
        Announcement.created_at.desc()
    ).all()
    
    user_id = session.get('user_id')
    result = []
    for ann in announcements:
        read = AnnouncementRead.query.filter_by(
            announcement_id=ann.id,
            user_id=user_id
        ).first() if user_id else None
        
        result.append({
            'id': ann.id,
            'title': ann.title,
            'content': ann.content,
            'created_by': ann.created_by,
            'is_pinned': ann.is_pinned,
            'is_read': bool(read),
            'created_at': ann.created_at.strftime('%Y-%m-%d %H:%M')
        })
    
    return jsonify(result)

@app.route('/api/announcements/<int:aid>/read', methods=['POST'])
def mark_announcement_read(aid):
    """Elon o'qildi deb belgilash"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    existing = AnnouncementRead.query.filter_by(
        announcement_id=aid,
        user_id=user_id
    ).first()
    
    if not existing:
        read = AnnouncementRead(announcement_id=aid, user_id=user_id)
        db.session.add(read)
        db.session.commit()
    
    return jsonify({'ok': True})

@app.route('/api/announcements/<int:aid>/pin', methods=['POST'])
def pin_announcement(aid):
    """Elon qo'l bilan qo'yish"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    ann = Announcement.query.get_or_404(aid)
    if ann.created_by != user_id:
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    ann.is_pinned = not ann.is_pinned
    db.session.commit()
    
    return jsonify({'ok': True, 'is_pinned': ann.is_pinned})

# ─── API: Schedule & Calendar ─────────────────────────────────────────

@app.route('/api/schedule', methods=['POST'])
def create_schedule():
    """Dars jadavali qo'shish"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    if not user or user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    d = request.json or {}
    group_id = d.get('group_id')
    title = d.get('title', '')
    event_type = d.get('event_type', 'lesson')
    start_time_str = d.get('start_time', '')
    end_time_str = d.get('end_time', '')
    
    try:
        start_time = datetime.fromisoformat(start_time_str)
        end_time = datetime.fromisoformat(end_time_str) if end_time_str else None
    except:
        return jsonify({'ok': False, 'error': 'Vaqt formati noto\'g\'ri'}), 400
    
    schedule = Schedule(
        group_id=group_id,
        title=title,
        event_type=event_type,
        start_time=start_time,
        end_time=end_time
    )
    db.session.add(schedule)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': schedule.id})

@app.route('/api/schedule/<int:gid>', methods=['GET'])
def get_schedule(gid):
    """Jadovalini olish"""
    schedules = Schedule.query.filter_by(group_id=gid).order_by(Schedule.start_time).all()
    
    return jsonify([{
        'id': s.id,
        'title': s.title,
        'event_type': s.event_type,
        'start_time': s.start_time.isoformat(),
        'end_time': s.end_time.isoformat() if s.end_time else None
    } for s in schedules])

# ─── API: Resource Library ────────────────────────────────────────────

@app.route('/api/resources', methods=['POST'])
def create_resource():
    """Resurs qo'shish (PDF, link, va hokazolar)"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    if not user or user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    d = request.json or {}
    group_id = d.get('group_id')
    title = d.get('title', '')
    file_type = d.get('file_type', 'link')
    file_url = d.get('file_url', '')
    description = d.get('description', '')
    
    resource = Resource(
        group_id=group_id,
        uploaded_by=user_id,
        title=title,
        file_type=file_type,
        file_url=file_url,
        description=description
    )
    db.session.add(resource)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': resource.id})

@app.route('/api/resources/<int:gid>', methods=['GET'])
def get_resources(gid):
    """Guruh resurslari"""
    resources = Resource.query.filter_by(group_id=gid).order_by(Resource.created_at.desc()).all()
    
    return jsonify([{
        'id': r.id,
        'title': r.title,
        'description': r.description,
        'file_type': r.file_type,
        'file_url': r.file_url,
        'uploaded_by': r.uploaded_by,
        'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
    } for r in resources])

# ─── API: Attendance Tracking ─────────────────────────────────────────

@app.route('/api/attendance', methods=['POST'])
def mark_attendance():
    """Qatnashni belgilash"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    if not user or user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    d = request.json or {}
    attendance_data = d.get('attendance', [])  # [{'user_id': 1, 'status': 'present'}, ...]
    group_id = d.get('group_id')
    date = d.get('date', datetime.now().date().isoformat())
    
    try:
        date_obj = datetime.fromisoformat(date).date()
    except:
        date_obj = datetime.now().date()
    
    for item in attendance_data:
        student_id = item.get('user_id')
        status = item.get('status', 'present')
        
        att = Attendance.query.filter_by(
            user_id=student_id,
            group_id=group_id,
            date=date_obj
        ).first()
        
        if att:
            att.status = status
        else:
            att = Attendance(
                user_id=student_id,
                group_id=group_id,
                status=status,
                date=date_obj
            )
            db.session.add(att)
    
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/attendance/<int:gid>', methods=['GET'])
def get_attendance(gid):
    """Qatnash raporti"""
    group = Group.query.get_or_404(gid)
    
    attendance_records = Attendance.query.filter_by(group_id=gid).order_by(Attendance.date.desc()).all()
    
    result = {}
    for att in attendance_records:
        if att.user_id not in result:
            result[att.user_id] = {
                'user_id': att.user_id,
                'user_name': att.user.name,
                'present': 0,
                'absent': 0,
                'late': 0
            }
        
        if att.status == 'present':
            result[att.user_id]['present'] += 1
        elif att.status == 'absent':
            result[att.user_id]['absent'] += 1
        elif att.status == 'late':
            result[att.user_id]['late'] += 1
    
    return jsonify(list(result.values()))

# ─── API: Video Hosting & Streaming ───────────────────────────────────

@app.route('/api/videos', methods=['POST'])
def upload_video():
    """Video yuklash"""
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    if not user or user.role != 'teacher':
        return jsonify({'ok': False, 'error': 'Ruxsat etilmagan'}), 403
    
    d = request.json or {}
    group_id = d.get('group_id')
    title = d.get('title', '')
    video_url = d.get('video_url', '')
    duration = d.get('duration', 0)
    description = d.get('description', '')
    
    video = Video(
        group_id=group_id,
        uploaded_by=user_id,
        title=title,
        video_url=video_url,
        duration=duration,
        description=description
    )
    db.session.add(video)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': video.id})

@app.route('/api/videos/<int:gid>', methods=['GET'])
def get_videos(gid):
    """Guruh videolari"""
    videos = Video.query.filter_by(group_id=gid).order_by(Video.created_at.desc()).all()
    
    user_id = session.get('user_id')
    result = []
    for v in videos:
        progress = VideoProgress.query.filter_by(
            user_id=user_id,
            video_id=v.id
        ).first() if user_id else None
        
        result.append({
            'id': v.id,
            'title': v.title,
            'description': v.description,
            'video_url': v.video_url,
            'duration': v.duration,
            'uploaded_by': v.uploaded_by,
            'created_at': v.created_at.strftime('%Y-%m-%d %H:%M'),
            'progress': {
                'current_time': progress.current_time if progress else 0,
                'is_completed': progress.is_completed if progress else False,
                'watch_time': progress.watch_time if progress else 0
            } if user_id else None
        })
    
    return jsonify(result)

@app.route('/api/video/<int:vid>/progress', methods=['POST'])
def save_video_progress(vid):
    """Video ko'rish progres saqlash"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    d = request.json or {}
    current_time = d.get('current_time', 0)
    watch_time = d.get('watch_time', 0)
    is_completed = d.get('is_completed', False)
    
    progress = VideoProgress.query.filter_by(
        user_id=user_id,
        video_id=vid
    ).first()
    
    if progress:
        progress.current_time = current_time
        progress.watch_time = watch_time
        progress.is_completed = is_completed
        progress.updated_at = datetime.utcnow()
    else:
        progress = VideoProgress(
            user_id=user_id,
            video_id=vid,
            current_time=current_time,
            watch_time=watch_time,
            is_completed=is_completed
        )
        db.session.add(progress)
    
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/video/<int:vid>/progress', methods=['GET'])
def get_video_progress(vid):
    """Video progres olish"""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Kirish zarur'}), 401
    
    progress = VideoProgress.query.filter_by(
        user_id=user_id,
        video_id=vid
    ).first()
    
    if not progress:
        return jsonify({'current_time': 0, 'is_completed': False, 'watch_time': 0})
    
    return jsonify({
        'current_time': progress.current_time,
        'is_completed': progress.is_completed,
        'watch_time': progress.watch_time
    })

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
