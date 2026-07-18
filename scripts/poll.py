import httpx
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import pathlib
import os
import tempfile

FEEDS = {
    "rssnews": "https://cbr.ru/rss/RssNews",
    "navr":    "https://cbr.ru/rss/navr",
    "project": "https://cbr.ru/rss/project",
}

DATA_DIR = pathlib.Path("data")

def load_existing(path: pathlib.Path):
    """Возвращает (root, channel, {guid: item_element}) или (None, None, {}) если файла нет"""
    if not path.exists():
        return None, None, {}
    tree = ET.parse(path)
    root = tree.getroot()
    channel = root.find("channel")
    items = {}
    for item in channel.findall("item"):
        guid_el = item.find("guid")
        if guid_el is not None and guid_el.text:
            items[guid_el.text] = item
    return root, channel, items

def pub_date_key(item):
    date_el = item.find("pubDate")
    try:
        return parsedate_to_datetime(date_el.text)
    except Exception:
        return parsedate_to_datetime("Thu, 01 Jan 1970 00:00:00 +0000")

def merge_feed(name: str, url: str):
    path = DATA_DIR / f"{name}.xml"
    resp = httpx.get(url, timeout=15)
    resp.raise_for_status()

    fresh_root = ET.fromstring(resp.content)
    fresh_channel = fresh_root.find("channel")
    fresh_items = fresh_channel.findall("item")

    existing_root, existing_channel, existing_by_guid = load_existing(path)

    new_count = 0
    if existing_root is None:
        # первый запуск — используем свежий ответ как базу
        existing_root = fresh_root
        existing_channel = fresh_channel
        existing_by_guid = {
            it.find("guid").text: it
            for it in fresh_items if it.find("guid") is not None
        }
        new_count = len(fresh_items)
    else:
        for item in fresh_items:
            guid_el = item.find("guid")
            if guid_el is None or guid_el.text is None:
                continue
            guid = guid_el.text
            if guid not in existing_by_guid:
                existing_channel.append(item)
                existing_by_guid[guid] = item
                new_count += 1

    # пересортировать item по pubDate, свежие сверху
    all_items = existing_channel.findall("item")
    all_items.sort(key=pub_date_key, reverse=True)
    for it in all_items:
        existing_channel.remove(it)
    for it in all_items:
        existing_channel.append(it)

    # атомарная запись
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".xml")
    os.close(fd)
    ET.ElementTree(existing_root).write(tmp_path, encoding="utf-8", xml_declaration=True)
    os.replace(tmp_path, path)

    return new_count, len(all_items)

def poll_all():
    for name, url in FEEDS.items():
        try:
            new_count, total = merge_feed(name, url)
            print(f"{name}: +{new_count} новых, всего {total}")
        except Exception as e:
            print(f"{name}: ошибка опроса — {e}")

if __name__ == "__main__":
    poll_all()