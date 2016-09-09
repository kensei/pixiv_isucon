CREATE INDEX post_id_idx ON comments (post_id);
CREATE INDEX post_id_created_at_idx ON comments (post_id, created_at);
CREATE INDEX user_id_created_at_idx ON posts (user_id, created_at);
