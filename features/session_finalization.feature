Feature: Session finalization
  When a conversation goes idle, the sweeper folds it into durable memory so
  nothing is lost even though the hot cache expires.

  Scenario: An idle session is folded into durable memory
    Given a fresh conversation
    And sessions are finalized as soon as they go idle
    When the user says "I am 小明 and I love tennis"
    And the idle sweeper runs
    Then the session is marked finalized
    And a durable channel summary exists
