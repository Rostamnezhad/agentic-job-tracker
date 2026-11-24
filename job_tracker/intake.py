"""Transparent, deterministic intake and preference checks. No model or network calls."""

import re
from .models import JobEntry

WORK_MODES = ('unknown', 'remote', 'hybrid', 'onsite')
JOB_TYPES = ('unknown', 'working_student', 'internship', 'full_time', 'part_time', 'contract')
LANGUAGES = ('unknown', 'english', 'german', 'mixed')
LEVELS = ('unknown', 'none', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2')
LABELS = {'working_student': 'Working student', 'internship': 'Internship', 'full_time': 'Full time',
          'part_time': 'Part time', 'contract': 'Contract', 'remote': 'Remote', 'hybrid': 'Hybrid',
          'onsite': 'On site', 'english': 'English', 'german': 'German', 'mixed': 'English and German'}


def text(data, key, maximum, default=''):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f'{key.replace("_", " ").capitalize()} must be text, at most {maximum} characters.')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError(f'{key} contains unsupported control characters.')
    return value.strip()


def choice(data, key, choices, default='unknown'):
    value = data.get(key, default)
    if value not in choices:
        raise ValueError(f'Choose a supported {key.replace("_", " ")}.')
    return value


def number(data, key, maximum):
    value = data.get(key)
    if value is None or value == '':
        return None
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'{key.replace("_", " ").capitalize()} must be a whole number from 0 to {maximum}.')
    return value


def validate_job(data):
    job = JobEntry(
        company=text(data, 'company', 120), role=text(data, 'role', 180),
        url=text(data, 'url', 2000), status=data.get('status', 'saved'),
        applied_date=data.get('applied_date') or None,
    )
    return {
        'company': job.company, 'role': job.role, 'url': job.url,
        'status': job.status, 'applied_date': job.applied_date,
        'location': text(data, 'location', 180),
        'work_mode': choice(data, 'work_mode', WORK_MODES),
        'employment_type': choice(data, 'employment_type', JOB_TYPES),
        'language': choice(data, 'language', LANGUAGES),
        'german_level': choice(data, 'german_level', LEVELS),
        'office_days': number(data, 'office_days', 5),
        'commute_minutes': number(data, 'commute_minutes', 600),
        'description': text(data, 'description', 20000), 'notes': text(data, 'notes', 5000),
    }


def validate_preferences(data):
    return {
        'locations': text(data, 'locations', 500), 'skills': text(data, 'skills', 500),
        'work_mode': choice(data, 'work_mode', WORK_MODES),
        'employment_type': choice(data, 'employment_type', JOB_TYPES),
        'language': choice(data, 'language', LANGUAGES),
        'german_level': choice(data, 'german_level', LEVELS),
        'office_days': number(data, 'office_days', 5),
        'commute_minutes': number(data, 'commute_minutes', 600),
    }


def split_items(value):
    return list(dict.fromkeys(x.strip() for x in value.split(',') if x.strip()))


def mention(term, source):
    return bool(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', source, re.IGNORECASE))


def assess(job, preferences):
    matches, gaps, unknowns = [], [], []
    for field, title in [('work_mode', 'Work arrangement'), ('employment_type', 'Job type'), ('language', 'Working language')]:
        desired = preferences.get(field, 'unknown')
        actual = job.get(field, 'unknown')
        if desired == 'unknown':
            continue
        if actual == 'unknown':
            unknowns.append(f'{title} is not confirmed.')
        elif actual == desired:
            matches.append(f'{title}: {LABELS[actual]}.')
        else:
            gaps.append(f'{title}: {LABELS[actual]}; you prefer {LABELS[desired]}.')
    for field, title, unit in [('office_days', 'Office attendance', 'days/week'), ('commute_minutes', 'One-way commute', 'minutes')]:
        maximum, actual = preferences.get(field), job.get(field)
        if maximum is None:
            continue
        if actual is None:
            unknowns.append(f'{title} needs checking against your {maximum} {unit} limit.')
        elif actual > maximum:
            gaps.append(f'{title}: {actual} {unit}, above your {maximum} limit.')
        else:
            matches.append(f'{title}: {actual} {unit}, within your limit.')
    level = preferences.get('german_level', 'unknown')
    required = job.get('german_level', 'unknown')
    if level != 'unknown':
        if required == 'unknown':
            unknowns.append('German requirement is not confirmed.')
        elif LEVELS.index(level) < LEVELS.index(required):
            gaps.append(f'German {required} requested; your level is {level if level != "none" else "not yet started"}.')
        else:
            matches.append('German requirement is within your stated level.')
    places = split_items(preferences.get('locations', ''))
    if places and job.get('work_mode') != 'remote':
        location = job.get('location', '')
        if not location:
            unknowns.append('Office location is not confirmed.')
        elif any(mention(place, location) for place in places):
            matches.append('Location matches one of your preferred places.')
        else:
            gaps.append(f'Location ({location}) is outside your listed preferences.')
    skills = split_items(preferences.get('skills', ''))
    source = job.get('role', '') + '\n' + job.get('description', '')
    found = [skill for skill in skills if mention(skill, source)]
    if found:
        matches.append('Your skills mentioned in the posting: ' + ', '.join(found) + '.')
    if skills and not found:
        unknowns.append('None of your listed skills was found in the pasted text; review the requirements.')
    return {'matches': matches, 'gaps': gaps, 'unknowns': unknowns}


def extract_description(description):
    """Suggest explicitly labelled fields. Unlabelled information stays unknown."""
    if not isinstance(description, str) or not 20 <= len(description.strip()) <= 20000:
        raise ValueError('Paste a job description between 20 and 20,000 characters.')
    result = {'description': description.strip(), 'status': 'saved'}
    aliases = {
        'company': r'company|employer|unternehmen',
        'role': r'role|job title|position|title|stelle',
        'url': r'url|job url|link', 'location': r'location|office location|standort',
    }
    for key, label in aliases.items():
        match = re.search(r'^(?:' + label + r')\s*:\s*(.+)$', description, re.I | re.M)
        if match:
            result[key] = match.group(1).strip()
    if not result.get('url'):
        match = re.search(r'https?://[^\s<>]+', description)
        if match:
            result['url'] = match.group(0).rstrip('.,;)')
    for key, labels, mapping in [
        ('work_mode', r'work mode|work arrangement|workplace', {'remote':'remote','fully remote':'remote','hybrid':'hybrid','on site':'onsite','onsite':'onsite','on-site':'onsite'}),
        ('employment_type', r'job type|employment type|contract type', {v.lower():k for k,v in LABELS.items() if k in JOB_TYPES}),
        ('language', r'working language|language', {'english':'english','german':'german','english and german':'mixed'}),
    ]:
        match = re.search(r'^(?:' + labels + r')\s*:\s*([^\n\r]+)', description, re.I | re.M)
        if match and match.group(1).strip().lower() in mapping:
            result[key] = mapping[match.group(1).strip().lower()]
    match = re.search(r'^german(?: level| requirement)?\s*:\s*(A1|A2|B1|B2|C1|C2|none)\s*$', description, re.I | re.M)
    if match:
        result['german_level'] = 'none' if match.group(1).lower() == 'none' else match.group(1).upper()
    return result
