Feature: Account access and abuse protection
  The API is gated by accounts; chatting needs a login; repeated auth
  attempts are throttled.

  Scenario: A new user can register and identify themselves
    When a visitor registers as "john@example.com"
    Then they can fetch their own profile

  Scenario: The same email cannot register twice
    When a visitor registers as "john@example.com"
    And another visitor registers as "john@example.com"
    Then the second registration is rejected

  Scenario: Chatting requires a login
    When a visitor sends a chat message without logging in
    Then the request is rejected as unauthorized

  Scenario: Repeated auth attempts are throttled
    Given auth attempts are limited to 2 per minute
    When a visitor makes 3 login attempts
    Then the last attempt is rejected for too many requests

  Scenario: A logged-in user gets an assistant reply
    When a visitor registers as "john@example.com"
    And they send the chat message "hello there"
    Then they receive an assistant reply mentioning "hello there"
