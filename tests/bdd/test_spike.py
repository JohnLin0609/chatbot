from pytest_bdd import parsers, scenarios, then, when

scenarios("spike.feature")


@when(parsers.parse('the user says "{text}"'))
def user_says(world, text):
    world.user_says(text)


@then(parsers.parse('the reply contains "{fragment}"'))
def reply_contains(world, fragment):
    assert fragment in world.last_reply
