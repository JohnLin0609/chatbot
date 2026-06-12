Feature: Conversation memory
  The assistant keeps context within a conversation, and durable storage
  backfills the context when the fast cache is gone.

  Scenario: The assistant sees earlier turns in the same conversation
    Given a fresh conversation
    When the user says "My name is 小明"
    And the user says "What is my name?"
    Then the prompt shown to the model includes "My name is 小明"

  Scenario: Memory survives a cache expiry
    Given a fresh conversation
    When the user says "I love tennis"
    And the conversation cache expires
    And the user says "What do I love?"
    Then the prompt shown to the model includes "I love tennis"
