Feature: Knowledge retrieval with citations
  Course material relevant to the question is pulled into the prompt with a
  readable citation, and every retrieval is recorded for offline evaluation.

  Scenario: A knowledge question pulls course material into the prompt
    Given the knowledge base contains a document "退費政策" with content "退費需於 30 天內申請"
    When the user says "退費規則是什麼?"
    Then the prompt shown to the model includes "退費需於 30 天內申請"
    And the prompt cites "退費政策"

  Scenario: The retrieval is recorded for offline evaluation
    Given the knowledge base contains a document "退費政策" with content "退費需於 30 天內申請"
    When the user says "退費規則是什麼?"
    Then an evaluation trace records the retrieved chunk
