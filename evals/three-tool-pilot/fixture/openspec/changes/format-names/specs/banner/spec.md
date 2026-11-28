## ADDED Requirements

### Requirement: Normalize banner names

The banner SHALL trim surrounding name whitespace unless verbatim mode is requested.

#### Scenario: Padded name

- **WHEN** the caller supplies "  Ada  " in normal mode
- **THEN** the banner reads "Hello, Ada!"

#### Scenario: Explicit verbatim mode

- **WHEN** the caller supplies "  Ada  " with --verbatim
- **THEN** the banner reads "Hello,   Ada  !"
