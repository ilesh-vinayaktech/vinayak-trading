-- A person can run a paper account and a live account side by side. `paper_account.user_id` is now the ACCOUNT KEY every account table already uses
-- (paper_event, paper_order, paper_run, paper_equity, the book): for a paper account it is still the person's own id, so nothing existing changes;
-- a live account has its own key (derived from the owner, see algo/paper/book.py `account_key`). The person is `owner_user_id`; one account per mode.
ALTER TABLE paper_account ADD COLUMN owner_user_id UUID;
UPDATE paper_account SET owner_user_id = user_id;
ALTER TABLE paper_account ALTER COLUMN owner_user_id SET NOT NULL;
ALTER TABLE paper_account ADD CONSTRAINT paper_account_owner_fkey FOREIGN KEY (owner_user_id) REFERENCES portal_user(user_id);
ALTER TABLE paper_account DROP CONSTRAINT paper_account_user_id_fkey;
ALTER TABLE paper_account ADD CONSTRAINT paper_account_one_per_mode UNIQUE (owner_user_id, mode);
