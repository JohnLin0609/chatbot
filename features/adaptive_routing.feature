Feature: Adaptive retrieval routing
  Simple messages skip retrieval entirely; complex questions get the full
  retrieve-and-rerank treatment; a broken knowledge base never blocks a reply.

  Scenario: A simple greeting skips knowledge retrieval
    Given the knowledge base contains a document "退費政策" with content "退費需於 30 天內申請"
    And the router classifies messages as simple
    When the user says "hi"
    Then the reply is produced without consulting the knowledge base

  Scenario: A complex question retrieves and reranks knowledge
    Given the knowledge base contains a document "退費政策" with content "退費需於 30 天內申請"
    And the router classifies messages as complex
    When the user says "退費規則是什麼?"
    Then the prompt shown to the model includes "退費需於 30 天內申請"
    And the knowledge was reranked

  Scenario: Knowledge base failure still produces a reply
    Given the knowledge base is unavailable
    When the user says "退費規則是什麼?"
    Then the assistant still replies
