Feature: Spike
  Throwaway compatibility check: pytest-bdd 8.1.0 + pytest 9 + asyncio.Runner World.

  Scenario: The pipeline produces a reply
    When the user says "hello"
    Then the reply contains "hello"
