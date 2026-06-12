Feature: Reply feedback
  Users rate assistant replies; the ratings aggregate for the admin view.

  Scenario: A user rates a reply thumbs-down
    When a visitor registers as "john@example.com"
    And they send the chat message "hello"
    And they rate the reply thumbs-down
    Then the feedback summary shows 1 negative rating
