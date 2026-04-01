import atexit
import contextlib
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from typing import List, Tuple
from viphoneme import vi2IPA

try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None

VIPHONEME_AVAILABLE = True
_VIPHONEME_WORKDIR = None
_VINORM_ISOLATED_PARENT = None


def _get_viphoneme_workdir() -> str:
    global _VIPHONEME_WORKDIR
    if _VIPHONEME_WORKDIR is None:
        _VIPHONEME_WORKDIR = tempfile.mkdtemp(prefix="viphoneme_")
        atexit.register(shutil.rmtree, _VIPHONEME_WORKDIR, ignore_errors=True)
    return _VIPHONEME_WORKDIR


def _ensure_vinorm_isolated() -> None:
    global _VINORM_ISOLATED_PARENT
    if os.environ.get("VIPHONEME_ISOLATE_VINORM", "1") not in {"1", "true", "True", "YES", "yes"}:
        return
    if _VINORM_ISOLATED_PARENT is not None:
        return

    spec = importlib.util.find_spec("vinorm")
    if spec is None or spec.origin is None:
        return

    src_dir = os.path.dirname(spec.origin)
    if not os.path.isfile(os.path.join(src_dir, "__init__.py")):
        return

    parent = tempfile.mkdtemp(prefix="vinorm_")
    dst_dir = os.path.join(parent, "vinorm")
    os.makedirs(dst_dir, exist_ok=True)

    shutil.copy2(os.path.join(src_dir, "__init__.py"), os.path.join(dst_dir, "__init__.py"))

    for name in os.listdir(src_dir):
        if name in {"__init__.py", "__pycache__", "input.txt", "output.txt"}:
            continue
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.exists(dst):
            continue
        try:
            os.symlink(src, dst)
        except Exception:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)

    if parent not in sys.path:
        sys.path.insert(0, parent)
    if "vinorm" in sys.modules:
        del sys.modules["vinorm"]

    _VINORM_ISOLATED_PARENT = parent
    atexit.register(shutil.rmtree, parent, ignore_errors=True)


@contextlib.contextmanager
def _redirect_fds_to_devnull():
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_stdout_fd = os.dup(1)
    saved_stderr_fd = os.dup(2)
    try:
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(saved_stdout_fd, 1)
        os.dup2(saved_stderr_fd, 2)
        os.close(saved_stdout_fd)
        os.close(saved_stderr_fd)
        os.close(devnull_fd)


@contextlib.contextmanager
def _viphoneme_global_lock():
    lock_path = os.environ.get("VIPHONEME_LOCK_PATH", "/tmp/viphoneme.lock")
    use_lock = os.environ.get("VIPHONEME_USE_LOCK")
    if use_lock is None:
        use_lock = "0" if os.environ.get("VIPHONEME_ISOLATE_VINORM", "1") in {"1", "true", "True", "YES", "yes"} else "1"
    if use_lock not in {"1", "true", "True", "YES", "yes"}:
        yield
        return
    if fcntl is None:
        yield
        return
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ============================================================
# SYLLABLE-STRUCTURE G2P ENGINE
# Port từ vietnamese_g2p.js — khắc phục lỗi đọc như người nước ngoài
# Phân tích: onset + nucleus + coda + tone (đúng chuẩn âm vị học)
# ============================================================

# Onset consonants (phụ âm đầu)
_Cus_onsets = {
    'b': 'b', 't': 't', 'th': 'tʰ', 'đ': 'd', 'ch': 'c',
    'kh': 'x', 'g': 'ɣ', 'l': 'l', 'm': 'm', 'n': 'n',
    'ngh': 'ŋ', 'nh': 'ɲ', 'ng': 'ŋ', 'ph': 'f', 'v': 'v',
    'x': 's', 'd': 'z', 'h': 'h', 'p': 'p', 'qu': 'kw',
    'gi': 'j', 'tr': 'ʈ', 'k': 'k', 'c': 'k', 'gh': 'ɣ',
    'r': 'ʐ', 's': 'ʂ',
}

# Nuclei — nguyên âm đơn + đôi (đầy đủ dấu thanh)
_Cus_nuclei = {
    'a':'a','á':'a','à':'a','ả':'a','ã':'a','ạ':'a',
    'â':'ɤ̆','ấ':'ɤ̆','ầ':'ɤ̆','ẩ':'ɤ̆','ẫ':'ɤ̆','ậ':'ɤ̆',
    'ă':'ă','ắ':'ă','ằ':'ă','ẳ':'ă','ẵ':'ă','ặ':'ă',
    'e':'ɛ','é':'ɛ','è':'ɛ','ẻ':'ɛ','ẽ':'ɛ','ẹ':'ɛ',
    'ê':'e','ế':'e','ề':'e','ể':'e','ễ':'e','ệ':'e',
    'i':'i','í':'i','ì':'i','ỉ':'i','ĩ':'i','ị':'i',
    'o':'ɔ','ó':'ɔ','ò':'ɔ','ỏ':'ɔ','õ':'ɔ','ọ':'ɔ',
    'ô':'o','ố':'o','ồ':'o','ổ':'o','ỗ':'o','ộ':'o',
    'ơ':'ɤ','ớ':'ɤ','ờ':'ɤ','ở':'ɤ','ỡ':'ɤ','ợ':'ɤ',
    'u':'u','ú':'u','ù':'u','ủ':'u','ũ':'u','ụ':'u',
    'ư':'ɯ','ứ':'ɯ','ừ':'ɯ','ử':'ɯ','ữ':'ɯ','ự':'ɯ',
    'y':'i','ý':'i','ỳ':'i','ỷ':'i','ỹ':'i','ỵ':'i',
    # Diphthongs
    'eo':'eo','éo':'eo','èo':'eo','ẻo':'eo','ẽo':'eo','ẹo':'eo',
    'êu':'ɛu','ếu':'ɛu','ều':'ɛu','ểu':'ɛu','ễu':'ɛu','ệu':'ɛu',
    'ia':'iə','ía':'iə','ìa':'iə','ỉa':'iə','ĩa':'iə','ịa':'iə',
    'iá':'iə','ià':'iə','iả':'iə','iã':'iə','iạ':'iə',
    'iê':'iə','iế':'iə','iề':'iə','iể':'iə','iễ':'iə','iệ':'iə',
    'oo':'ɔ','óo':'ɔ','òo':'ɔ','ỏo':'ɔ','õo':'ɔ','ọo':'ɔ',
    'oó':'ɔ','oò':'ɔ','oỏ':'ɔ','oõ':'ɔ','oọ':'ɔ',
    'ua':'uə','úa':'uə','ùa':'uə','ủa':'uə','ũa':'uə','ụa':'uə',
    'uô':'uə','uố':'uə','uồ':'uə','uổ':'uə','uỗ':'uə','uộ':'uə',
    'ưa':'ɯə','ứa':'ɯə','ừa':'ɯə','ửa':'ɯə','ữa':'ɯə','ựa':'ɯə',
    'ươ':'ɯə','ướ':'ɯə','ườ':'ɯə','ưở':'ɯə','ưỡ':'ɯə','ượ':'ɯə',
    'yê':'iɛ','yế':'iɛ','yề':'iɛ','yể':'iɛ','yễ':'iɛ','yệ':'iɛ',
    'uơ':'uə','uở':'uə','uờ':'uə','uỡ':'uə','uợ':'uə',
}

# Offglides — nguyên âm + bán âm cuối (bao gồm triphthongs)
_Cus_offglides = {
    'ai':'aj','ái':'aj','ài':'aj','ải':'aj','ãi':'aj','ại':'aj',
    'ay':'ăj','áy':'ăj','ày':'ăj','ảy':'ăj','ãy':'ăj','ạy':'ăj',
    'ao':'aw','áo':'aw','ào':'aw','ảo':'aw','ão':'aw','ạo':'aw',
    'au':'ăw','áu':'ăw','àu':'ăw','ảu':'ăw','ãu':'ăw','ạu':'ăw',
    'ây':'ɤ̆j','ấy':'ɤ̆j','ầy':'ɤ̆j','ẩy':'ɤ̆j','ẫy':'ɤ̆j','ậy':'ɤ̆j',
    'âu':'ɤ̆w','ấu':'ɤ̆w','ầu':'ɤ̆w','ẩu':'ɤ̆w','ẫu':'ɤ̆w','ậu':'ɤ̆w',
    'eo':'ew','éo':'ew','èo':'ew','ẻo':'ew','ẽo':'ew','ẹo':'ew',
    'iu':'iw','íu':'iw','ìu':'iw','ỉu':'iw','ĩu':'iw','ịu':'iw',
    'oi':'ɔj','ói':'ɔj','òi':'ɔj','ỏi':'ɔj','õi':'ɔj','ọi':'ɔj',
    'ôi':'oj','ối':'oj','ồi':'oj','ổi':'oj','ỗi':'oj','ội':'oj',
    'ui':'uj','úi':'uj','ùi':'uj','ủi':'uj','ũi':'uj','ụi':'uj',
    'uy':'ʷi','úy':'uj','ùy':'uj','ủy':'uj','ũy':'uj','ụy':'uj',
    'uý':'ʷi','uỳ':'ʷi','uỷ':'ʷi','uỹ':'ʷi','uỵ':'ʷi',
    'ơi':'ɤj','ới':'ɤj','ời':'ɤj','ởi':'ɤj','ỡi':'ɤj','ợi':'ɤj',
    'ưi':'ɯj','ứi':'ɯj','ừi':'ɯj','ửi':'ɯj','ữi':'ɯj','ựi':'ɯj',
    'ưu':'ɯw','ứu':'ɯw','ừu':'ɯw','ửu':'ɯw','ữu':'ɯw','ựu':'ɯw',
    # Triphthongs
    'iêu':'iəw','iếu':'iəw','iều':'iəw','iểu':'iəw','iễu':'iəw','iệu':'iəw',
    'yêu':'iəw','yếu':'iəw','yều':'iəw','yểu':'iəw','yễu':'iəw','yệu':'iəw',
    'uôi':'uəj','uối':'uəj','uồi':'uəj','uổi':'uəj','uỗi':'uəj','uội':'uəj',
    'ươi':'ɯəj','ưới':'ɯəj','ười':'ɯəj','ưởi':'ɯəj','ưỡi':'ɯəj','ượi':'ɯəj',
    'ươu':'ɯəw','ướu':'ɯəw','ườu':'ɯəw','ưởu':'ɯəw','ưỡu':'ɯəw','ượu':'ɯəw',
}

# Onglides — bán âm đầu (labialized)
_Cus_onglides = {
    'oa':'ʷa','oá':'ʷa','oà':'ʷa','oả':'ʷa','oã':'ʷa','oạ':'ʷa',
    'óa':'ʷa','òa':'ʷa','ỏa':'ʷa','õa':'ʷa','ọa':'ʷa',
    'oă':'ʷă','oắ':'ʷă','oằ':'ʷă','oẳ':'ʷă','oẵ':'ʷă','oặ':'ʷă',
    'oe':'ʷɛ','oé':'ʷɛ','oè':'ʷɛ','oẻ':'ʷɛ','oẽ':'ʷɛ','oẹ':'ʷɛ',
    'óe':'ʷɛ','òe':'ʷɛ','ỏe':'ʷɛ','õe':'ʷɛ','ọe':'ʷɛ',
    'ua':'ʷa','uá':'ʷa','uà':'ʷa','uả':'ʷa','uã':'ʷa','uạ':'ʷa',
    'uă':'ʷă','uắ':'ʷă','uằ':'ʷă','uẳ':'ʷă','uẵ':'ʷă','uặ':'ʷă',
    'uâ':'ʷɤ̆','uấ':'ʷɤ̆','uầ':'ʷɤ̆','uẩ':'ʷɤ̆','uẫ':'ʷɤ̆','uậ':'ʷɤ̆',
    'ue':'ʷɛ','ué':'ʷɛ','uè':'ʷɛ','uẻ':'ʷɛ','uẽ':'ʷɛ','uẹ':'ʷɛ',
    'uê':'ʷe','uế':'ʷe','uề':'ʷe','uể':'ʷe','uễ':'ʷe','uệ':'ʷe',
    'uơ':'ʷɤ','uớ':'ʷɤ','uờ':'ʷɤ','uở':'ʷɤ','uỡ':'ʷɤ','uợ':'ʷɤ',
    'uy':'ʷi','uý':'ʷi','uỳ':'ʷi','uỷ':'ʷi','uỹ':'ʷi','uỵ':'ʷi',
    'uya':'ʷiə','uyá':'ʷiə','uyà':'ʷiə','uyả':'ʷiə','uyã':'ʷiə','uyạ':'ʷiə',
    'uyê':'ʷiə','uyế':'ʷiə','uyề':'ʷiə','uyể':'ʷiə','uyễ':'ʷiə','uyệ':'ʷiə',
}

# Onoff glides
_Cus_onoffglides = {
    'oai':'aj','oái':'aj','oài':'aj','oải':'aj','oãi':'aj','oại':'aj',
    'oay':'ăj','oáy':'ăj','oày':'ăj','oảy':'ăj','oãy':'ăj','oạy':'ăj',
    'oao':'aw','oáo':'aw','oào':'aw','oảo':'aw','oão':'aw','oạo':'aw',
    'oeo':'ew','oéo':'ew','oèo':'ew','oẻo':'ew','oẽo':'ew','oẹo':'ew',
    'uai':'aj','uái':'aj','uài':'aj','uải':'aj','uãi':'aj','uại':'aj',
    'uay':'ăj','uáy':'ăj','uày':'ăj','uảy':'ăj','uãy':'ăj','uạy':'ăj',
    'uây':'ɤ̆j','uấy':'ɤ̆j','uầy':'ɤ̆j','uẩy':'ɤ̆j','uẫy':'ɤ̆j','uậy':'ɤ̆j',
}

# Coda consonants (phụ âm cuối)
_Cus_codas = {
    'p':'p','t':'t','c':'k','m':'m','n':'n',
    'ng':'ŋ','nh':'ɲ','ch':'tʃ',
}

# Thanh điệu: dấu → số (1=ngang,2=huyền,3=ngã,4=hỏi,5=sắc,6=nặng)
_Cus_tones = {
    'á':5,'à':2,'ả':4,'ã':3,'ạ':6,
    'ấ':5,'ầ':2,'ẩ':4,'ẫ':3,'ậ':6,
    'ắ':5,'ằ':2,'ẳ':4,'ẵ':3,'ặ':6,
    'é':5,'è':2,'ẻ':4,'ẽ':3,'ẹ':6,
    'ế':5,'ề':2,'ể':4,'ễ':3,'ệ':6,
    'í':5,'ì':2,'ỉ':4,'ĩ':3,'ị':6,
    'ó':5,'ò':2,'ỏ':4,'õ':3,'ọ':6,
    'ố':5,'ồ':2,'ổ':4,'ỗ':3,'ộ':6,
    'ớ':5,'ờ':2,'ở':4,'ỡ':3,'ợ':6,
    'ú':5,'ù':2,'ủ':4,'ũ':3,'ụ':6,
    'ứ':5,'ừ':2,'ử':4,'ữ':3,'ự':6,
    'ý':5,'ỳ':2,'ỷ':4,'ỹ':3,'ỵ':6,
}

# Trường hợp đặc biệt: 'gi' đứng một mình
_Cus_gi = {
    'gi':'zi','gí':'zi','gì':'zi','gỉ':'zi','gĩ':'zi','gị':'zi',
}

# Mapping tone: viphoneme(1-6) → internal(0-5)
_TONE_MAP = {1:0, 2:2, 3:3, 4:4, 5:1, 6:5}

# Dấu câu
PUNCTUATION = set(',.!?;:\'"—-…()[]{}')


def _trans_syllable(word: str) -> dict:
    """
    Phân tích một âm tiết thành onset+nucleus+coda+tone.
    Port 1-1 từ hàm trans() trong vietnamese_g2p.js.
    Returns: {'ons', 'nuc', 'cod', 'ton', 'is_oov'}
    """
    word = unicodedata.normalize('NFC', word).lower()
    l = len(word)
    if l == 0:
        return {'ons':'','nuc':'','cod':'','ton':1,'is_oov':False}

    ons = ''; nuc = ''; cod = ''; ton = 1
    o_offset = 0; c_offset = 0

    # Onset: trigraph → digraph → đơn
    if l >= 3 and word[:3] in _Cus_onsets:
        ons = _Cus_onsets[word[:3]]; o_offset = 3
    elif l >= 2 and word[:2] in _Cus_onsets:
        ons = _Cus_onsets[word[:2]]; o_offset = 2
    elif word[0] in _Cus_onsets:
        ons = _Cus_onsets[word[0]]; o_offset = 1

    # Coda: digraph → đơn
    if l >= 2 and word[l-2:] in _Cus_codas:
        cod = _Cus_codas[word[l-2:]]; c_offset = 2
    elif word[l-1] in _Cus_codas:
        cod = _Cus_codas[word[l-1]]; c_offset = 1

    nucl = word[o_offset: l - c_offset if c_offset else l]

    # Đặc biệt: 'gi' + coda (3 ký tự, không phải hỏi)
    _i_no_hoi = 'iíìĩị'
    if word[0] == 'g' and l == 3 and len(word) > 1 and word[1] in _i_no_hoi and cod:
        nucl = 'i'; ons = 'z'

    # Khớp nucleus theo thứ tự ưu tiên
    if nucl in _Cus_nuclei:
        nuc = _Cus_nuclei[nucl]
    elif nucl in _Cus_onglides and ons != 'kw':
        nuc = _Cus_onglides[nucl]
        ons = (ons + 'w') if ons else 'w'
    elif nucl in _Cus_onglides and ons == 'kw':
        nuc = _Cus_onglides[nucl]
    elif nucl in _Cus_onoffglides:
        glide = _Cus_onoffglides[nucl]
        cod = glide[-1]; nuc = glide[:-1]
        if ons != 'kw':
            ons = (ons + 'w') if ons else 'w'
    elif nucl in _Cus_offglides:
        glide = _Cus_offglides[nucl]
        cod = glide[-1]; nuc = glide[:-1]
    elif word in _Cus_gi:
        ons = _Cus_gi[word][0]; nuc = _Cus_gi[word][1]
    else:
        return {'ons':'','nuc':word,'cod':'','ton':1,'is_oov':True}

    # Trích xuất thanh điệu
    for ch in word:
        if ch in _Cus_tones:
            ton = _Cus_tones[ch]; break

    # Velar Fronting (phương ngữ Bắc): anh→ɛɲ, ach→ɛk
    if nuc == 'a' and cod == 'ɲ': nuc = 'ɛ'
    if nuc == 'a' and cod == 'k' and c_offset == 2: nuc = 'ɛ'

    return {'ons':ons,'nuc':nuc,'cod':cod,'ton':ton,'is_oov':False}


def _ipa_to_phones(ipa_str: str) -> List[str]:
    """Tách chuỗi IPA → danh sách phoneme, xử lý modifier và combining marks."""
    phones = []
    i = 0
    while i < len(ipa_str):
        ch = ipa_str[i]
        if unicodedata.combining(ch):
            i += 1; continue
        if ch in ('ʷ', 'ʰ', 'ː'):
            if phones: phones[-1] += ch
            i += 1; continue
        if ch in ('\u0361', '\u035c'):
            i += 1; continue
        phones.append(ch)
        i += 1
    return phones


def text_to_phonemes_viphoneme(text: str) -> Tuple[List[str], List[int], List[int]]:
    """
    Convert text to phonemes using viphoneme library.
    Returns (phones, tones, word2ph)
    
    viphoneme output format:
    - Syllables separated by space
    - Compound words joined by underscore: hom1_năj1
    - Tone number (1-6) at end of each syllable
    - Punctuation as separate tokens
    """
    import warnings
    
    # Call viphoneme (ICU warnings will appear but won't affect results)
    # Note: viphoneme may not work on Windows due to platform-specific binaries
    try:
        _ensure_vinorm_isolated()
        workdir = _get_viphoneme_workdir()
        with _viphoneme_global_lock():
            cwd = os.getcwd()
            os.chdir(workdir)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with _redirect_fds_to_devnull():
                        ipa_text = vi2IPA(text)
            finally:
                os.chdir(cwd)
    except Exception:
        # Fallback to char-based on error (e.g., Windows compatibility issues)
        return text_to_phonemes_charbased(text)
    
    # Check if viphoneme returned empty or invalid result
    if not ipa_text or ipa_text.strip() in ['', '.', '..', '...']:
        return text_to_phonemes_charbased(text)
    
    phones = []
    tones = []
    word2ph = []
    
    # viphoneme tone mapping: 1=ngang, 2=huyền, 3=ngã, 4=hỏi, 5=sắc, 6=nặng
    # Our internal: 0=ngang, 1=sắc, 2=huyền, 3=ngã, 4=hỏi, 5=nặng
    VIPHONEME_TONE_MAP = {1: 0, 2: 2, 3: 3, 4: 4, 5: 1, 6: 5}
    
    # Characters to skip (combining marks, ties)
    SKIP_CHARS = {'\u0306', '\u0361', '\u032f', '\u0330', '\u0329'}  # breve, tie, etc.
    
    # Split by space
    tokens = ipa_text.strip().split()
    
    for token in tokens:
        # Handle punctuation-only tokens
        if all(c in PUNCTUATION or c == '.' for c in token):
            for c in token:
                if c in PUNCTUATION:
                    phones.append(c)
                    tones.append(0)
                    word2ph.append(1)
            continue
        
        # Split compound words by underscore
        syllables = token.split('_')
        
        for syllable in syllables:
            if not syllable:
                continue
                
            syllable_phones = []
            syllable_tone = 0
            i = 0
            
            while i < len(syllable):
                char = syllable[i]
                
                # Tone number at end
                if char.isdigit():
                    syllable_tone = VIPHONEME_TONE_MAP.get(int(char), 0)
                    i += 1
                    continue
                
                # Skip combining marks (they modify previous char, already handled)
                if unicodedata.combining(char):
                    i += 1
                    continue
                
                # Skip modifier letters like ʷ ʰ (append to previous if exists)
                if char in {'ʷ', 'ʰ', 'ː'}:
                    if syllable_phones:
                        syllable_phones[-1] = syllable_phones[-1] + char
                    i += 1
                    continue
                
                # Skip tie bars and other special marks
                if char in {'\u0361', '\u035c', '\u0361'}:  # tie bars
                    i += 1
                    continue
                
                # Punctuation within syllable
                if char in PUNCTUATION:
                    i += 1
                    continue
                
                # Regular phoneme character
                syllable_phones.append(char)
                i += 1
            
            if syllable_phones:
                phones.extend(syllable_phones)
                tones.extend([syllable_tone] * len(syllable_phones))
                word2ph.append(len(syllable_phones))
    
    return phones, tones, word2ph


def text_to_phonemes_charbased(text: str) -> Tuple[List[str], List[int], List[int]]:
    """
    Chuyển văn bản tiếng Việt → (phones, tones, word2ph).
    Dùng phân tích cấu trúc âm tiết đúng chuẩn (onset+nucleus+coda+tone).
    Port từ vietnamese_g2p.js — khắc phục lỗi đọc như người nước ngoài.
    """
    phones: List[str] = []
    tones: List[int] = []
    word2ph: List[int] = []

    for word in text.split():
        if not word:
            continue

        # Tách dấu câu đầu
        leading_punct: List[str] = []
        while word and word[0] in PUNCTUATION:
            leading_punct.append(word[0]); word = word[1:]

        # Tách dấu câu cuối
        trailing_punct: List[str] = []
        while word and word[-1] in PUNCTUATION:
            trailing_punct.insert(0, word[-1]); word = word[:-1]

        for p in leading_punct:
            phones.append(p); tones.append(0); word2ph.append(1)

        if word:
            r = _trans_syllable(word)
            if r['is_oov']:
                # Từ không phải tiếng Việt: giữ nguyên từng ký tự
                for ch in word:
                    phones.append(ch); tones.append(0); word2ph.append(1)
            else:
                ipa_str = r['ons'] + r['nuc'] + r['cod']
                syl_phones = _ipa_to_phones(ipa_str)
                if syl_phones:
                    internal_tone = _TONE_MAP.get(r['ton'], 0)
                    phones.extend(syl_phones)
                    tones.extend([internal_tone] * len(syl_phones))
                    word2ph.append(len(syl_phones))

        for p in trailing_punct:
            phones.append(p); tones.append(0); word2ph.append(1)

    return phones, tones, word2ph


def text_to_phonemes(text: str, use_viphoneme: bool = True) -> Tuple[List[str], List[int], List[int]]:
    """
    Main function to convert Vietnamese text to phonemes.
    
    Args:
        text: Vietnamese text
        use_viphoneme: Whether to use viphoneme library (if available)
        
    Returns:
        phones: List of IPA phonemes
        tones: List of tone numbers (0-5)
        word2ph: List of phone counts per word
    """
    if use_viphoneme and VIPHONEME_AVAILABLE:
        phones, tones, word2ph = text_to_phonemes_viphoneme(text)
    else:
        phones, tones, word2ph = text_to_phonemes_charbased(text)
    
    # Add boundary tokens
    phones = ["_"] + phones + ["_"]
    tones = [0] + tones + [0]
    word2ph = [1] + word2ph + [1]
    
    return phones, tones, word2ph


def get_all_phonemes() -> List[str]:
    """Get list of all possible phonemes for symbol table."""
    phonemes = set()
    
    # From IPA mapping
    for ipa in VI_TO_IPA.values():
        if isinstance(ipa, str):
            phonemes.add(ipa)
            # Also add with length marker
            if len(ipa) == 1:
                phonemes.add(ipa + 'ː')
    
    # Common IPA symbols
    phonemes.update([
        # Consonants
        'b', 'ɓ', 'c', 'd', 'ɗ', 'f', 'g', 'ɣ', 'h', 'j', 'k', 'l', 'm', 'n',
        'ŋ', 'ɲ', 'p', 'r', 'ʐ', 's', 'ʂ', 't', 'tʰ', 'ʈ', 'v', 'w', 'x', 'z',
        # Vowels
        'a', 'aː', 'ə', 'əː', 'ɛ', 'e', 'i', 'ɪ', 'o', 'ɔ', 'u', 'ʊ', 'ɯ', 'ɤ',
        # Special
        '_', ' ',
    ])
    
    # Punctuation
    phonemes.update(PUNCTUATION)
    
    return sorted(list(phonemes))