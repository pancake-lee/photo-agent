DROP TABLE IF EXISTS abandon_code;
CREATE TABLE abandon_code (
  idx1 INT NOT NULL AUTO_INCREMENT COMMENT 'The primary key of the table',
  col1 varchar(32)  NOT NULL,

  idx2 int NOT NULL,
  idx3 int NOT NULL,

  PRIMARY KEY (idx1),
  UNIQUE KEY idx_2_3 (idx2, idx3)
) COMMENT='CURD生成模板' AUTO_INCREMENT=10;
