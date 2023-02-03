# for now, run like:
#   GH_USER=user GH_TOKEN=$(cat /path/to/token/file) python tools/gen_entry_json.py
# get a token from here: https://github.com/settings/tokens

import os
import re
import sys
import json
import time
import base64
import urllib.request
import datetime
from pprint import pprint

import yaml
from boltons.urlutils import URL
from boltons.fileutils import atomic_save
from boltons.timeutils import isoparse

TOOLS_PATH = os.path.dirname(os.path.abspath(__file__))
PROJ_PATH = os.path.dirname(TOOLS_PATH)

PREFIXES = ['v',     # common
            'rel-',  # theano
            'orc-',  # orc
            'tor-',  # tor
            'clamav-',  # ...
            'streamex-',  # ...
            'nw-v',  # nw.js
]


VTAG_RE = re.compile(r'^(?P<major>\d+)\.[0-9a-zA-Z_.]+')

def strip_prefix(tag_name, prefixes):
    # TODO: could combine these all into the re
    for prefix in prefixes:
        if tag_name.startswith(prefix):
            tag_name = tag_name[len(prefix):]
            break
    return tag_name


def match_vtag(tag_name, prefixes):
    tag_name = strip_prefix(tag_name, prefixes)
    return VTAG_RE.match(tag_name)


def version_key(version, prefixes=PREFIXES):
    return tuple([int(x) for x in
                  re.split('\D', match_vtag(version, prefixes).group(0))
                  if x and x.isdigit()])


def _get_gh_json(url):
    """"
    Get paginated results from GitHub, possibly authorized based on
    GH_USER/GH_TOKEN env vars.
    """
    gh_token = os.getenv('GH_TOKEN', '')
    req = urllib.request.Request(url)
    if gh_token:
        auth_header_val = f'token {gh_token}'
        req.add_header('Authorization', auth_header_val)
    resp = urllib.request.urlopen(req)
    body = resp.read()
    res = json.loads(body)
    rate_rem = int(resp.headers.get('x-ratelimit-remaining', '-1'))

    if not isinstance(res, list) or not res:
        print(' (( %s requests remaining' % rate_rem)
        return res
    page = 2
    ret = res
    while res:
        paged_url = url + '?page=%s' % page
        req = urllib.request.Request(paged_url)
        if gh_token:
            req.add_header('Authorization', auth_header_val)
        resp = urllib.request.urlopen(req)
        body = resp.read()
        res = json.loads(body)
        ret.extend(res)
        page += 1
    rate_rem = int(resp.headers.get('x-ratelimit-remaining', '-1'))
    print(' (( %s requests remaining' % rate_rem)
    return ret


def _get_gh_rel_data(rel_info, prefixes):
    ret = {}
    ret['tag'] = rel_info['name']
    ret['version'] = None
    if match_vtag(ret['tag'], prefixes):
        ret['version'] = strip_prefix(ret['tag'], prefixes)
    ret['api_commit_url'] = rel_info['commit']['url']
    rel_data = _get_gh_json(ret['api_commit_url'])
    ret['date'] = rel_data['commit']['author']['date']
    ret['link'] = rel_data['html_url']
    return ret


def get_gh_project_info(info):
    ret = {}
    url = info.get('gh_url')
    if url is None:
        return ret

    org, repo = URL(url.rstrip('/')).path_parts[1:]
    gh_url = URL('https://api.github.com/repos')
    gh_url.path_parts += (org, repo)

    project_url = gh_url.to_text()
    project_data = _get_gh_json(project_url)
    ret['star_count'] = project_data['stargazers_count']

    gh_url.path_parts += ('tags',)
    tags_url = gh_url.to_text()
    tags_data = _get_gh_json(tags_url)
    vtags_data = [td for td in tags_data if match_vtag(td['name'], PREFIXES)]

    ret['release_count'] = len(vtags_data)

    latest_release = vtags_data[0]
    latest_release_data = _get_gh_rel_data(latest_release, PREFIXES)
    for k, v in latest_release_data.items():
        ret['latest_release_%s' % k] = v

    vtags_data.sort(key=lambda x: version_key(x['name'], PREFIXES), reverse=True)

    first_release_version = info.get('first_release_version')
    if first_release_version is None:
        first_release = [v for v in vtags_data
                         if version_key(v['name']) < version_key(latest_release['name'])][-1]
    else:
        first_release = [v for v in vtags_data if v['name'] == first_release_version][0]
    first_release_data = _get_gh_rel_data(first_release, PREFIXES)
    for k, v in first_release_data.items():
        ret['first_release_%s' % k] = v

    zv_releases = [rel for rel in vtags_data
                   if match_vtag(rel['name'], PREFIXES).group('major') == '0']
    ret['release_count_zv'] = len(zv_releases)
    print(' .. %s releases, %s 0ver' % (ret['release_count'], ret['release_count_zv']))

    is_zerover = latest_release in zv_releases

    ret['is_zerover'] = is_zerover

    if is_zerover:
        return ret

    last_zv_release = zv_releases[0]
    first_nonzv_release = vtags_data[vtags_data.index(last_zv_release) - 1]
    first_nonzv_release_data = _get_gh_rel_data(first_nonzv_release, PREFIXES)

    ret['last_zv_release_version'] = last_zv_release['name']
    for k, v in first_nonzv_release_data.items():
        ret['first_nonzv_release_%s' % k] = v

    #import pdb;pdb.set_trace()

    return ret


def _json_default(obj):
    # yaml likes to parse some dates
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError ("%r is not serializable" % obj)


def fetch_entries(projects):
    entries = []

    for p in projects:
        print('processing', p['name'])
        info = dict(p)
        if info.get('skip'):
            continue

        info['url'] = info.get('url', info.get('gh_url'))

        if info.get('gh_url'):
            try:
                gh_info = get_gh_project_info(info)
                info.update(gh_info)
            except:
                pass

        info['is_zerover'] = info.get('is_zerover', not info.get('emeritus', False))

        entries.append(info)

    return entries


def _main():
    start_time = time.time()
    with open(PROJ_PATH + '/projects.yaml') as f:
        projects = yaml.safe_load(f)['projects']
    #projects = [p for p in projects if p['name'] == 'scikit-learn']
    #if not projects:
    #    return
    try:
        with open(PROJ_PATH + '/projects.json') as f:
            cur_data = json.load(f)
            cur_projects = cur_data['projects']
            cur_gen_date = isoparse(cur_data['gen_date'])
    except (IOError, KeyError):
        cur_projects = []
        cur_gen_date = None

    if cur_gen_date:
        fetch_outdated = (datetime.datetime.utcnow() - cur_gen_date) > datetime.timedelta(seconds=3600)
    else:
        fetch_outdated = True
    cur_names = sorted([c['name'] for c in cur_projects])
    new_names = sorted([n['name'] for n in projects])

    tpr = os.getenv('TRAVIS_PULL_REQUEST')
    if tpr and tpr != 'false':
        print('Pull request detected. Skipping data update until merged.')
        return
    if fetch_outdated or cur_names != new_names or os.getenv('ZV_DISABLE_CACHING'):
        entries = fetch_entries(projects)
    else:
        print('Current data already up to date, exiting.')
        return

    pprint(entries)

    res = {'projects': entries,
           'gen_date': datetime.datetime.utcnow().isoformat(),
           'gen_duration': time.time() - start_time}

    with atomic_save(PROJ_PATH + '/projects.json', text_mode=True) as f:
        f.write(json.dumps(res, indent=2, sort_keys=True, default=_json_default))

    return


if __name__ == '__main__':
    try:
        sys.exit(_main() or 0)
    except Exception as e:
        if os.getenv('CI'):
            raise
        print(' !! debugging unexpected %r' % e)
        # import pdb;pdb.post_mortem()
        raise
