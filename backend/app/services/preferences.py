from copy import deepcopy
from app.db.models import PersonalPreference, Setting


def defaults(config):
    return {'search_engine':config['search']['default'], 'clock_format':config['clock'].get('format','24h'),
            'timezone':config['clock'].get('timezone','Asia/Seoul'), 'weather_location':config['temperature']['location'],
            'temperature_scale':config['temperature']['scale'], 'animation_mode':'system' if config.get('tabAnimation',True) else 'off'}


def preferences(db, user_id):
    base = defaults(db.get(Setting,'portal').value)
    row = db.get(PersonalPreference,user_id)
    values = row.values if row else {}
    return {'overrides':values, 'defaults':base, 'effective':base | values}


def apply_preferences(db, user_id, config):
    config = deepcopy(config)
    row = db.get(PersonalPreference,user_id)
    values = defaults(config) | (row.values if row else {})
    config['search']['default'] = values['search_engine']
    config['clock']['format'] = values['clock_format']; config['clock']['timezone'] = values['timezone']
    config['temperature']['location'] = values['weather_location']; config['temperature']['scale'] = values['temperature_scale']
    config['animationMode'] = values['animation_mode']
    return config
