import datetime
import os
import re
import pathlib
import subprocess
# import tempfile

import flask
import MySQLdb.cursors
import logging
from pymemcache.client.base import Client as MemcacheClient
# http://flask.pocoo.org/snippets/28/
from jinja2 import evalcontextfilter, Markup, escape

import pymc_session


# 10mb
UPLOAD_LIMIT = 10 * 1024 * 1024
POSTS_PER_PAGE = 20
POSTS_LIMIT = 25
ACCOUNT_ID_KEY_PREFIX = 'ACCOUNT_ID'
ACCOUNT_NAME_KEY_PREFIX = 'ACCOUNT_NAME'


_config = None


def config():
    global _config
    if _config is None:
        _config = {
            "db": {
                "host": os.environ.get("ISUCONP_DB_HOST", 'localhost'),
                "port": int(os.environ.get("ISUCONP_DB_PORT", "3306")),
                "user": os.environ.get("ISUCONP_DB_USER", "root"),
                "db": os.environ.get("ISUCONP_DB_NAME", "isuconp"),
            },
        }
        password = os.environ.get("ISUCONP_DB_PASSWORD")
        if password:
            _config['db']['passwd'] = password
    return _config


_db = None


def db():
    global _db
    if _db is None:
        conf = config()["db"].copy()
        conf['charset'] = 'utf8mb4'
        conf['cursorclass'] = MySQLdb.cursors.DictCursor
        conf['autocommit'] = True
        _db = MySQLdb.connect(**conf)
    return _db


def db_initialize():
    cur = db().cursor()
    sqls = [
        'DELETE FROM users WHERE id > 1000',
        'DELETE FROM posts WHERE id > 10000',
        'DELETE FROM comments WHERE id > 100000',
        'UPDATE users SET del_flg = 0',
        'UPDATE users SET del_flg = 1 WHERE id % 50 = 0',
    ]
    for q in sqls:
        cur.execute(q)


def memcache_initialize():
    cursor = db().cursor()
    cursor.execute('SELECT id, account_name, passhash, authority, del_flg FROM `users`')
    users = cursor.fetchall()
    for user in users:
        set_account_by_id(user['id'], user['account_name'], 0, user['authority'])
        set_account_by_name(user['account_name'], user['id'], user['passhash'])


_mcclient = None


def memcache():
    global _mcclient
    if _mcclient is None:
        _mcclient = MemcacheClient(('127.0.0.1', 11211), no_delay=True, default_noreply=False)
    return _mcclient


def try_login(account_name, password):
    cur = db().cursor()
    cur.execute("SELECT * FROM users WHERE account_name = %s AND del_flg = 0", (account_name,))
    user = cur.fetchone()

    if user and calculate_passhash(user["account_name"], password) == user["passhash"]:
        return user
    return None


def validate_user(account_name: str, password: str):
    if not re.match(r"[0-9a-zA-Z]{3,}", account_name):
        return False
    if not re.match(r"[0-9a-zA-Z_]{6,}", password):
        return False
    return True


def digest(src: str):
    out = subprocess.check_output(["openssl", "dgst", "-sha512"], input=src.encode('ascii'))
    out = out.decode('ascii')
    # opensslのバージョンによっては (stdin)= というのがつくので取る
    out = out[out.find('=') + 1:]
    return out.strip()


def calculate_salt(account_name: str):
    return digest(account_name)


def calculate_passhash(account_name: str, password: str):
    return digest("%s:%s" % (password, calculate_salt(account_name)))


def get_session_user():
    user = flask.session.get('user')
    if user:
        # cur = db().cursor()
        # cur.execute("SELECT id, authority FROM `users` WHERE `id` = %s", (user['id'],))
        # return cur.fetchone()
        account_name, del_flg, authority = get_account_by_id(user['id'])
        return {'id':user['id'], 'account_name':account_name, 'del_flg':del_flg, 'authority':authority}
    return None


def make_posts(results, all_comments=False):
    posts = []
    cursor = db().cursor()
    for post in results:
        # cursor.execute("SELECT COUNT(*) AS `count` FROM `comments` WHERE `post_id` = %s",
        #                (post['id'],))
        # post['comment_count'] = cursor.fetchone()

        query = 'SELECT * FROM `comments` WHERE `post_id` = %s ORDER BY `created_at` DESC'
        if not all_comments:
            query += ' LIMIT 3'

        cursor.execute(query, (post['id'],))
        comments = list(cursor)
        for comment in comments:
            # cursor.execute("SELECT * FROM `users` WHERE `id` = %s", (comment['user_id'],))
            # comment['user'] = cursor.fetchone()
            account_name, _, _ = get_account_by_id(comment['user_id'])
            comment['user'] = {'account_name', account_name}
        comments.reverse()
        post['comments'] = comments
        post['comment_count'] = len(comments) if all_comments else 3

        # cursor.execute("SELECT * FROM `users` WHERE `id` = %s", (post['user_id'],))
        # post['user'] = cursor.fetchone()
        account_name, del_flg, _ = get_account_by_id(post['user_id'])
        post['user'] = {'account_name' , account_name}

        # if not post['user']['del_flg']:
        if del_flg == 0:
            posts.append(post)

        if len(posts) >= POSTS_PER_PAGE:
            break
    return posts


def get_account_by_id(user_id: int):
    account_key = '{}_{}'.format(ACCOUNT_ID_KEY_PREFIX, user_id)
    account = memcache().get(account_key)
    if account is None:
        cursor = db().cursor()
        cursor.execute("SELECT account_name, authority, del_flg FROM `users` WHERE `id` = %s", (user_id,))
        account_data = cursor.fetchone()
        if account_data is None:
            return None, None, None
        account = set_account_by_id(user_id, account_data['account_name'], account_data['del_flg'], account_data['authority'])
    else:
        account = account.decode('utf-8')
    data = account.split(",")
    return data[0], int(data[1]), int(data[2])


def get_account_by_name(account_name: str):
    account_key = '{}_{}'.format(ACCOUNT_NAME_KEY_PREFIX, account_name)
    account = memcache().get(account_key)
    if account is None:
        cursor = db().cursor()
        cursor.execute("SELECT id, passhash FROM `users` WHERE `account_name` = %s", (account_name,))
        account_data = cursor.fetchone()
        if account_data is None:
            return None, None
        account = set_account_by_name(account_name, account_data['id'], account_data['passhash'])
    else:
        account = account.decode('utf-8')
    data = account.split(",")
    return int(data[0]), data[1]


def set_account_by_id(user_id: int, account_name: str, del_flg: int, authority: int):
    account_key = '{}_{}'.format(ACCOUNT_ID_KEY_PREFIX, user_id)
    account = '{},{},{}'.format(account_name, del_flg, authority)
    memcache().set(account_key, account)
    return account


def set_account_by_name(account_name: str, user_id: int, passhash: str):
    account_key = '{}_{}'.format(ACCOUNT_NAME_KEY_PREFIX, account_name)
    account = '{},{}'.format(user_id, passhash)
    memcache().set(account_key, account)
    return account


# app setup

static_path = pathlib.Path(__file__).resolve().parent.parent / 'public'
app = flask.Flask(__name__, static_folder=str(static_path), static_url_path='')
# app.debug = True
app.session_interface = pymc_session.SessionInterface(memcache())
app.logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
app.logger.addHandler(handler)


@app.template_global()
def image_url(post):
    ext = ""
    mime = post['mime']
    if mime == "image/jpeg":
        ext = ".jpg"
    elif mime == "image/png":
        ext = ".png"
    elif mime == "image/gif":
        ext = ".gif"

    return "/image/%s%s" % (post['id'], ext)


_paragraph_re = re.compile(r'(?:\r\n|\r|\n){2,}')


@app.template_filter()
@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p.replace('\n', '<br>\n') for p in _paragraph_re.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)


# endpoints


@app.route('/initialize')
def get_initialize():
    db_initialize()
    memcache_initialize()
    return ''


@app.route('/login')
def get_login():
    if get_session_user():
        return flask.redirect('/')
    return flask.render_template("login.html", me=None)


@app.route('/login', methods=['POST'])
def post_login():
    if get_session_user():
        return flask.redirect('/')

    user = try_login(flask.request.form['account_name'], flask.request.form['password'])
    if user:
        flask.session['user'] = {"id": user["id"]}
        flask.session['csrf_token'] = os.urandom(8).hex()
        return flask.redirect('/')

    flask.flash("アカウント名かパスワードが間違っています")
    return flask.redirect('/login')


@app.route('/register')
def get_register():
    if get_session_user():
        return flask.redirect('/')
    return flask.render_template("register.html", me=None)


@app.route('/register', methods=['POST'])
def post_register():
    if get_session_user():
        return flask.redirect('/')

    account_name = flask.request.form['account_name']
    password = flask.request.form['password']
    if not validate_user(account_name, password):
        flask.flash("アカウント名は3文字以上、パスワードは6文字以上である必要があります")
        return flask.redirect("/register")

    cursor = db().cursor()
    # cursor.execute("SELECT 1 FROM users WHERE `account_name` = %s", (account_name,))
    # user = cursor.fetchone()
    # if user:
    user_id, _ = get_account_by_name(account_name)
    if user_id is not None:
        flask.flash("アカウント名がすでに使われています")
        return flask.redirect("/register")

    query = 'INSERT INTO `users` (`account_name`, `passhash`) VALUES (%s, %s)'
    # cursor.execute(query, (account_name, calculate_passhash(account_name, password)))
    passhash = calculate_passhash(account_name, password)
    cursor.execute(query, (account_name, passhash))

    set_account_by_name(account_name, cursor.lastrowid, passhash)
    set_account_by_id(cursor.lastrowid, account_name, 0, 1)

    flask.session['user'] = {'id': cursor.lastrowid}
    flask.session['csrf_token'] = os.urandom(8).hex()
    return flask.redirect('/')


@app.route('/logout')
def get_logout():
    flask.session.clear()
    return flask.redirect('/')


@app.route('/')
def get_index():
    me = get_session_user()

    cursor = db().cursor()
    cursor.execute('SELECT `id`, `user_id`, `body`, `created_at`, `mime` FROM `posts` ORDER BY `created_at` DESC LIMIT %s', (POSTS_LIMIT,))
    posts = make_posts(cursor.fetchall())

    return flask.render_template("index.html", posts=posts, me=me)


@app.route('/@<account_name>')
def get_user_list(account_name):
    cursor = db().cursor()

    # cursor.execute("SELECT id, account_name FROM `users` WHERE `account_name` = %s AND `del_flg` = 0",
    #                (account_name,))
    # user = cursor.fetchone()
    # if not user:
    user_id, _ = get_account_by_name(account_name)
    if user_id is None:
        flask.abort(404)  # raises exception

    cursor.execute("SELECT `id`, `user_id`, `body`, `mime`, `created_at` FROM `posts` WHERE `user_id` = %s ORDER BY `created_at` DESC LIMIT %s",
                   (user_id, POSTS_LIMIT))
    #               (user['id'], POSTS_LIMIT))
    posts = make_posts(cursor.fetchall())

    # cursor.execute('SELECT COUNT(*) AS count FROM `comments` WHERE `user_id` = %s', (user['id'],))
    cursor.execute('SELECT COUNT(*) AS count FROM `comments` WHERE `user_id` = %s', (user_id,))
    comment_count = cursor.fetchone()['count']

    # cursor.execute('SELECT `id` FROM `posts` WHERE `user_id` = %s', (user['id'],))
    cursor.execute('SELECT `id` FROM `posts` WHERE `user_id` = %s', (user_id,))
    post_ids = [p['id'] for p in cursor]
    post_count = len(post_ids)

    """
    commented_count = 0
    if post_count > 0:
        cursor.execute("SELECT COUNT(*) AS count FROM `comments` WHERE `post_id` IN %s", (post_ids,))
        commented_count = cursor.fetchone()['count']
    """

    me = get_session_user()

    # return flask.render_template("user.html",
    #                              posts=posts, user=user, post_count=post_count,
    #                              comment_count=comment_count, me=me)
    return flask.render_template("user.html",
                                 posts=posts, user={'account_name', account_name}, post_count=post_count,
                                 comment_count=comment_count, me=me)


def _parse_iso8601(s):
    # http://bugs.python.org/issue15873
    # Ignore timezone
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ tT](\d{2}):(\d{2}):(\d{2}).*', s)
    if not m:
        raise ValueError("Invlaid iso8601 format: %r" % (s,))
    return datetime.datetime(*map(int, m.groups()))


@app.route('/posts')
def get_posts():
    cursor = db().cursor()
    max_created_at = flask.request.args['max_created_at'] or None
    if max_created_at:
        max_created_at = _parse_iso8601(max_created_at)
        cursor.execute('SELECT `id`, `user_id`, `body`, `mime`, `created_at` FROM `posts` WHERE `created_at` <= %s ORDER BY `created_at` DESC LIMIT %s', (max_created_at, POSTS_LIMIT))
    else:
        cursor.execute('SELECT `id`, `user_id`, `body`, `mime`, `created_at` FROM `posts` WHERE ORDER BY `created_at` DESC LIMIT %s', (POSTS_LIMIT,))
    results = cursor.fetchall()
    posts = make_posts(results)
    return flask.render_template("posts.html", posts=posts)


@app.route('/posts/<id>')
def get_posts_id(id):
    cursor = db().cursor()

    cursor.execute("SELECT * FROM `posts` WHERE `id` = %s", (id,))
    posts = make_posts(cursor.fetchall(), all_comments=True)
    if not posts:
        flask.abort(404)

    me = get_session_user()
    return flask.render_template("post.html", post=posts[0], me=me)


@app.route('/', methods=['POST'])
def post_index():
    me = get_session_user()
    if not me:
        return flask.redirect('/login')

    if flask.request.form['csrf_token'] != flask.session['csrf_token']:
        flask.abort(422)

    file = flask.request.files.get('file')
    if not file:
        flask.flash("画像が必要です")
        return flask.redirect('/')

    # 投稿のContent-Typeからファイルのタイプを決定する
    mime = file.mimetype
    if mime not in ("image/jpeg", "image/png", "image/gif"):
        flask.flash("投稿できる画像形式はjpgとpngとgifだけです")
        return flask.redirect('/')

    """
    with tempfile.TemporaryFile() as tempf:
        file.save(tempf)
        tempf.flush()

        if tempf.tell() > UPLOAD_LIMIT:
            flask.flash("ファイルサイズが大きすぎます")
            return flask.redirect('/')

        tempf.seek(0)
        imgdata = tempf.read()
    """

    query = 'INSERT INTO `posts` (`user_id`, `mime`, `imgdata`, `body`) VALUES (%s,%s,%s,%s)'
    cursor = db().cursor()
    # cursor.execute(query, (me['id'], mime, imgdata, flask.request.form.get('body')))
    cursor.execute(query, (me['id'], mime, 'test', flask.request.form.get('body')))
    pid = cursor.lastrowid

    file_name = image_url({"id": pid, "mime": mime})
    file_path = str(static_path) + file_name
    if (os.path.exists(file_path)):
        os.remove(file_path)
    file.save(file_path)

    if os.path.getsize(file_path) > UPLOAD_LIMIT:
        flask.flash("ファイルサイズが大きすぎます")
        return flask.redirect('/')

    return flask.redirect("/posts/%d" % pid)


"""
@app.route('/image/<id>.<ext>')
def get_image(id, ext):
    if not id:
        return ""
    id = int(id)
    if id == 0:
        return ""

    cursor = db().cursor()
    cursor.execute('SELECT * FROM `posts` WHERE `id` = %s', (id,))
    post = cursor.fetchone()

    mime = post['mime']
    if (ext == 'jpg' and mime == "image/jpeg"\
            or ext == 'png' and mime == "image/png"\
            or ext == 'gif' and mime == "image/gif"):
        return flask.Response(post['imgdata'], mimetype=mime)

    flask.abort(404)
"""


@app.route('/comment', methods=['POST'])
def post_comment():
    me = get_session_user()
    if not me:
        return flask.redirect('/login')

    if flask.request.form['csrf_token'] != flask.session['csrf_token']:
        flask.abort(422)

    post_id = flask.request.form['post_id']
    if not re.match(r"[0-9]+", post_id):
        return 'post_idは整数のみです'
    post_id = int(post_id)

    query = 'INSERT INTO `comments` (`post_id`, `user_id`, `comment`) VALUES (%s, %s, %s)'
    cursor = db().cursor()
    cursor.execute(query, (post_id, me['id'], flask.request.form['comment']))

    return flask.redirect("/posts/%d" % post_id)


@app.route('/admin/banned')
def get_banned():
    me = get_session_user()
    if not me:
        flask.redirect('/login')

    if me['authority'] == 0:
        flask.abort(403)

    cursor = db().cursor()
    cursor.execute('SELECT id, account_name FROM `users` WHERE `authority` = 0 AND `del_flg` = 0 ORDER BY `created_at` DESC')
    users = cursor.fetchall()

    flask.render_template("banned.html", users=users, me=me)


@app.route('/admin/banned', methods=['POST'])
def post_banned():
    me = get_session_user()
    if not me:
        flask.redirect('/login')

    if me['authority'] == 0:
        flask.abort(403)

    if flask.request.form['csrf_token'] != flask.session['csrf_token']:
        flask.abort(422)

    cursor = db().cursor()
    query = 'UPDATE `users` SET `del_flg` = %s WHERE `id` = %s'
    for id in flask.request.form.getlist('uid', type=int):
        account_name, _, _ = get_account_by_id(id)
        set_account_by_id(id, account_name, 1)
        cursor.execute(query, (1, id))

    return flask.redirect('/admin/banned')
