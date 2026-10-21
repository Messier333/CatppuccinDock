"""Load bundled defaults and seed each user's portal once."""
import json
from importlib.resources import files

from app.db.models import Bookmark, Category, PortalSeed, Tab


def default_config():
    return json.loads(files("app.data").joinpath("startpage.json").read_text(encoding="utf-8"))


def seed_portal(db, user_id):
    if db.get(PortalSeed, user_id):
        return
    for tab_index, source in enumerate(default_config()["tabs"]):
        tab = Tab(user_id=user_id, name=source["name"], banner="none", position=tab_index)
        db.add(tab)
        db.flush()
        for category_index, source_category in enumerate(source["categories"]):
            category = Category(user_id=user_id, tab_id=tab.id, name=source_category["name"], position=category_index)
            db.add(category)
            db.flush()
            for position, link in enumerate(source_category["links"]):
                db.add(Bookmark(user_id=user_id, category_id=category.id, position=position, **(link | {'icon_color': 'auto'})))
    db.add(PortalSeed(user_id=user_id))
