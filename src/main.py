import logging
import re
from collections import defaultdict
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from prettytable import PrettyTable
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, PEP_DOC_URL
from outputs import control_output
from utils import find_tag, get_response, is_in_expected_statuses


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li',
        attrs={'class': 'toctree-l1'}
    )
    result = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор'), ]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        next_link = urljoin(whats_new_url, href)
        session.cache.clear()
        session = requests_cache.CachedSession()
        resp = get_response(session, next_link)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, features='lxml')
        h1_header = find_tag(soup, 'h1')
        dl_header = find_tag(soup, 'dl').text.replace('\n', ' ')
        result.append(
            (next_link, h1_header.text, dl_header)
        )
    return result


def latest_versions(session):
    resp = get_response(session, MAIN_DOC_URL)
    if resp is None:
        return
    soup = BeautifulSoup(resp.text, 'lxml')
    sidebar = find_tag(soup, 'div', attrs={'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise Exception('Не найден список c версиями Python')
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    results = []
    for a_tag in a_tags:
        text_match = re.search(pattern, a_tag.text)
        link = a_tag['href']
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )
    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    resp = get_response(session, downloads_url)
    if resp is None:
        return
    soup = BeautifulSoup(resp.text, 'lxml')
    table = find_tag(soup, 'table', attrs={'class': 'docutils'})
    ref = find_tag(table, 'a', attrs={'href': re.compile(r'.+pdf-a4\.zip$')})
    link = ref['href']
    archive_url = urljoin(downloads_url, link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    resp = get_response(session, PEP_DOC_URL)
    if resp is None:
        return
    soup = BeautifulSoup(resp.text, 'lxml')
    tables = find_tag(
        soup,
        'section',
        attrs={'id': 'index-by-category'}
    ).find_all('tr')

    different_statuses = []

    counters = defaultdict(lambda: 0)
    for raw in tqdm(tables):
        if not raw.abbr:
            continue
        status_on_main_page = list(find_tag(raw, 'abbr').text)
        next_link = urljoin(PEP_DOC_URL, find_tag(raw, 'a')['href'])
        response = session.get(next_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, 'lxml')
        status = find_tag(soup, 'abbr')
        if not is_in_expected_statuses(status.text, status_on_main_page):
            different_statuses.append((
                next_link,
                status.text,
                EXPECTED_STATUS[status_on_main_page[-1]],
            ))
            continue
        counters[status.text] += 1
    if different_statuses:
        msg = ['\n{0}\nВ карточке:{1}\nОжидал: {2}'.format(*info)
               for info in different_statuses]
        logging.info('Несовпадающие статусы:' + str(*msg))
    counters['Total'] = sum([*counters.values()])
    return counters.items()


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    yp_table = PrettyTable()
    main()
