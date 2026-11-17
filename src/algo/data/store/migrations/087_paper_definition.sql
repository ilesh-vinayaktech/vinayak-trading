-- A paper account can follow a generated strategy definition once its study has passed the global holdout. The account carries a copy of the
-- locked definition and the study's chosen settings (definition = {"definition", "universe", "experiment_id", "name"}), like screen does for a screener;
-- universe is then 'segments' (the study's own universe: market-cap classes and minimum history).
ALTER TABLE paper_account ADD COLUMN definition JSONB;
ALTER TABLE paper_account ADD CONSTRAINT paper_account_definition_check
  CHECK ((strategy_id = 'dsl') = (definition IS NOT NULL));
