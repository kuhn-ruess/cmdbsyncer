from application.models.states import State

def get_obj():
    try:
        current = State.objects()[0]
    except IndexError:
        current = State()
        current.open_changes = 0
    return current


def get_changes():
    current = get_obj()
    return current.open_changes


def add_changes(num=1):
    current = get_obj()
    current.open_changes += num
    current.save()


def remove_changes():
    current = get_obj()
    current.open_changes = False
    current.save()
