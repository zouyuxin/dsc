#!/usr/bin/env python
__author__ = "Gao Wang"
__copyright__ = "Copyright 2016, Stephens lab"
__email__ = "gaow@uchicago.edu"
__license__ = "MIT"
import sys, os, msgpack, yaml, re, glob, pickle
from collections import OrderedDict
import pandas as pd
from sos.utils import logger
from .dsc_database import ResultDBError
from .utils import load_rds, save_rds, \
     flatten_list, uniq_list, no_duplicates_constructor, \
     cartesian_list, extend_dict, strip_dict, \
     try_get_value, is_sublist
from .line import OperationParser

SQL_KEYWORDS = set([
    'ADD', 'ALL', 'ALTER', 'ANALYZE', 'AND', 'AS', 'ASC', 'ASENSITIVE', 'BEFORE',
    'BETWEEN', 'BIGINT', 'BINARY', 'BLOB', 'BOTH', 'BY', 'CALL', 'CASCADE', 'CASE',
    'CHANGE', 'CHAR', 'CHARACTER', 'CHECK', 'COLLATE', 'COLUMN', 'CONDITION',
    'CONSTRAINT', 'CONTINUE', 'CONVERT', 'CREATE', 'CROSS', 'CURRENT_DATE',
    'CURRENT_TIME', 'CURRENT_TIMESTAMP', 'CURRENT_USER', 'CURSOR', 'DATABASE',
    'DATABASES', 'DAY_HOUR', 'DAY_MICROSECOND', 'DAY_MINUTE', 'DAY_SECOND', 'DEC',
    'DECIMAL', 'DECLARE', 'DEFAULT', 'DELAYED', 'DELETE', 'DESC',
    'DESCRIBE', 'DETERMINISTIC', 'DISTINCT', 'DISTINCTROW', 'DIV', 'DOUBLE',
    'DROP', 'DUAL', 'EACH', 'ELSE', 'ELSEIF', 'ENCLOSED', 'ESCAPED', 'EXISTS',
    'EXIT', 'EXPLAIN', 'FALSE', 'FETCH', 'FLOAT', 'FLOAT4', 'FLOAT8', 'FOR',
    'FORCE', 'FOREIGN', 'FROM', 'FULLTEXT', 'GRANT', 'GROUP', 'HAVING', 'HIGH_PRIORITY',
    'HOUR_MICROSECOND', 'HOUR_MINUTE', 'HOUR_SECOND', 'IF', 'IGNORE', 'IN',
    'INDEX', 'INFILE', 'INNER', 'INOUT', 'INSENSITIVE', 'INSERT',
    'INT', 'INT1', 'INT2', 'INT3', 'INT4', 'INT8', 'INTEGER', 'INTERVAL', 'INTO',
    'IS', 'ITERATE', 'JOIN', 'KEY', 'KEYS', 'KILL', 'LEADING', 'LEAVE', 'LEFT',
    'LIKE', 'LIMIT', 'LINES', 'LOAD', 'LOCALTIME', 'LOCALTIMESTAMP',
    'LOCK', 'LONG', 'LONGBLOB', 'LONGTEXT', 'LOOP', 'LOW_PRIORITY', 'MATCH',
    'MEDIUMBLOB', 'MEDIUMINT', 'MEDIUMTEXT', 'MIDDLEINT', 'MINUTE_MICROSECOND',
    'MINUTE_SECOND', 'MOD', 'MODIFIES', 'NATURAL', 'NOT', 'NO_WRITE_TO_BINLOG',
    'NULL', 'NUMERIC', 'ON', 'OPTIMIZE', 'OPTION', 'OPTIONALLY', 'OR',
    'ORDER', 'OUT', 'OUTER', 'OUTFILE', 'PRECISION', 'PRIMARY', 'PROCEDURE',
    'PURGE', 'READ', 'READS', 'REAL', 'REFERENCES', 'REGEXP', 'RELEASE',
    'RENAME', 'REPEAT', 'REPLACE', 'REQUIRE', 'RESTRICT', 'RETURN',
    'REVOKE', 'RIGHT', 'RLIKE', 'SCHEMA', 'SCHEMAS', 'SECOND_MICROSECOND',
    'SELECT', 'SENSITIVE', 'SEPARATOR', 'SET', 'SHOW', 'SMALLINT',
    'SONAME', 'SPATIAL', 'SPECIFIC', 'SQL', 'SQLEXCEPTION', 'SQLSTATE',
    'SQLWARNING', 'SQL_BIG_RESULT', 'SQL_CALC_FOUND_ROWS', 'SQL_SMALL_RESULT',
    'SSL', 'STARTING', 'STRAIGHT_JOIN', 'TABLE', 'TERMINATED',
    'THEN', 'TINYBLOB', 'TINYINT', 'TINYTEXT', 'TO', 'TRAILING',
    'TRIGGER', 'TRUE', 'UNDO', 'UNION', 'UNIQUE', 'UNLOCK', 'UNSIGNED',
    'UPDATE', 'USAGE', 'USE', 'USING', 'UTC_DATE', 'UTC_TIME', 'UTC_TIMESTAMP', 'VALUES',
    'VARBINARY', 'VARCHAR', 'VARCHARACTER', 'VARYING', 'WHEN', 'WHERE', 'WHILE',
    'WITH', 'WRITE', 'XOR', 'YEAR_MONTH', 'ZEROFILL', 'ASENSITIVE', 'CALL', 'CONDITION',
    'CONNECTION', 'CONTINUE', 'CURSOR', 'DECLARE', 'DETERMINISTIC', 'EACH',
    'ELSEIF', 'EXIT', 'FETCH', 'GOTO', 'INOUT', 'INSENSITIVE', 'ITERATE', 'LABEL', 'LEAVE',
    'LOOP', 'MODIFIES', 'OUT', 'READS', 'RELEASE', 'REPEAT', 'RETURN', 'SCHEMA', 'SCHEMAS',
    'SENSITIVE', 'SPECIFIC', 'SQL', 'SQLEXCEPTION', 'SQLSTATE', 'SQLWARNING', 'TRIGGER',
    'UNDO', 'UPGRADE', 'WHILE', 'ABS', 'ACOS', 'ADDDATE', 'ADDTIME', 'ASCII', 'ASIN',
    'ATAN', 'AVG', 'BETWEEN', 'AND', 'BINARY', 'BIN', 'BIT_AND',
    'BIT_OR', 'CASE', 'CAST', 'CEIL', 'CHAR', 'CHARSET', 'CONCAT', 'CONV', 'COS', 'COT',
    'COUNT', 'DATE', 'DAY', 'DIV', 'EXP', 'IS', 'LIKE', 'MAX', 'MIN', 'MOD', 'MONTH',
    'LOG', 'POW', 'SIN', 'SLEEP', 'SORT', 'STD', 'VALUES', 'SUM'
])

def id_generator(size=6, chars=None):
    import string, random
    if chars is None:
        chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(size))

def expand_logic(string):
    PH = '__{}'.format(id_generator())
    string = string.replace('*', PH + '_ast__')
    string = string.replace('+', PH + '_plus__')
    string = string.replace(',', PH + '_com__')
    string = string.replace(' or ', ',')
    string = string.replace(' OR ', ',')
    string = string.replace(' and ', '*')
    string = string.replace(' AND ', '*')
    string = re.sub(' +',  PH + '_space__', string)
    res = []
    op = OperationParser()
    for x in op(string):
        if isinstance(x, str):
            x = (x,)
        tmp = []
        for y in x:
            y = y.replace(PH + '_ast__', '*')
            y = y.replace(PH + '_plus__', '+')
            y = y.replace(PH + '_com__', ',')
            y = y.replace(PH + '_space__', ' ')
            tmp.append(y)
        res.append(tmp)
    return res

class Query_Processor:
    def __init__(self, db, target, condition = None):
        self.db = db
        self.target = target
        self.condition = condition or []
        self.target_tables = self.parse_tables(self.target, allow_null = True)
        self.condition_tables = self.parse_tables(self.condition, allow_null = False)
        self.data = pickle.load(open(os.path.expanduser(db), 'rb'))
        # 1. only keep tables that do exist in database
        self.target_tables = self.filter_tables(self.target_tables)
        self.condition_tables = self.filter_tables(self.condition_tables)
        # 2. identify all pipelines in database
        self.pipelines = self.find_pipelines()
        # 3. identify which pipelines are minimally involved, based on tables in target / condition
        self.pipelines = self.filter_pipelines()
        # 4. make inner join, the FROM clause
        from_clauses = self.get_from_clause()
        # 5. make select / where clause
        select_clauses, where_clauses = self.get_select_where_clause()
        self.queries = [' '.join(x) for x in list(zip(*[select_clauses, from_clauses, where_clauses]))]

    @staticmethod
    def legalize_name(name, kw = False):
        output = ''
        for x in name:
            if re.match(r'^[a-zA-Z0-9_]+$', x):
                output += x
            else:
                output += '_'
        if re.match(r'^[0-9][a-zA-Z0-9_]+$', output) or (output.upper() in SQL_KEYWORDS and kw):
            output = '_' + output
        return output

    def parse_tables(self, values, allow_null):
        '''
        input is lists of strings
        output should be lists of tuples
        [(table, field), (table, field) ...]
        '''
        res = []
        for item in re.sub('[^0-9a-zA-Z_.]+', ' ', ' '.join(values)).split():
            if re.search('^\w+\.\w+$', item):
                x, y = item.split('.')
                if x == self.legalize_name(x) and y == self.legalize_name(y):
                    res.append((x, y))
            else:
                if allow_null and item == self.legalize_name(item, kw = True):
                    res.append((item, None))
        return res

    def filter_tables(self, tables):
        return uniq_list([x for x in tables if x[0].lower() in
                          [y.lower() for y in self.data.keys() if not y.startswith('pipeline_')]])

    def find_pipelines(self):
        '''
        example output:
        [('rnorm', 'mean', 'MSE'), ('rnorm', 'median', 'MSE'), ... ('rt', 'winsor', 'MSE')]
        '''
        masters = {k[:-8] : self.data[k] for k in self.data.keys()
                   if k.startswith("pipeline_") and k.endswith('.captain')}
        res = []
        for key in masters:
            for pipeline in masters[key]:
                new_pipeline = []
                for item in pipeline:
                    new_pipeline.append([x for x in uniq_list(self.data[key][item + '_name'].tolist()) if x != '-'])
                res.extend(cartesian_list(*new_pipeline))
        return res

    def filter_pipelines(self):
        '''
        for each pipeline, label whether or not each item is involved
        '''
        tables = [x[0].lower() for x in self.target_tables] + [x[0].lower() for x in self.condition_tables]
        indic = []
        for pipeline in self.pipelines:
            indic.append([x.lower() in tables for x in pipeline])
        res = []
        for x, y in zip(indic, self.pipelines):
            tmp = []
            for idx, item in enumerate(x):
                if item:
                    tmp.append(y[idx])
                else:
                    break
            res.append(tuple(tmp))
        res = uniq_list(res)
        max_res = []
        for x in res:
            include = True
            for y in res:
                if x == y:
                    continue
                if is_sublist(x, y):
                    include = False
                    break
            if include:
                max_res.append(x)
        return max_res

    def get_from_clause(self):
        res = []
        for pipeline in self.pipelines:
            pipeline = list(reversed(pipeline))
            res.append('FROM {0} '.format(pipeline[0]) + ' '.join(["INNER JOIN {1} ON {0}.parent = {1}.ID".format(pipeline[i], pipeline[i+1]) for i in range(len(pipeline) - 1)]))
        return res

    def get_select_where_clause(self):
        select = []
        where = []
        for pipeline in self.pipelines:
            tmp1 = []
            tmp2 = []
            for item in self.target_tables:
                if len([x for x in pipeline if x.lower() == item[0].lower()]) == 0:
                    continue
                tmp2.append(item)
                if item[1] is None:
                    tmp1.append("'{0}' AS {0}".format(item[0]))
                    continue
                key = [x for x in self.data.keys() if x.lower() == item[0].lower()][0]
                if item[1] not in [x.lower() for x in self.data[key].keys()]:
                    tmp1.append("{0}.FILE AS {0}_FILE_{1}".format(item[0], item[1]))
                else:
                    tmp1.append("{0}.{1} AS {0}_{1}".format(item[0], item[1]))
            select.append("SELECT " + ', '.join(tmp1))
            where.append(self.get_one_where_clause([x[0].lower() for x in tmp2]))
        return select, where

    def get_one_where_clause(self, tables):
        '''
        After expanding, condition is a list of list
        the outer lists are connected by OR
        the inner lists are connected by AND
        '''
        # to decide which part of the conditions is relevant to which pipeline we have to
        # dissect it to reveal table/field names
        condition = []
        for each_and in expand_logic(' AND '.join(self.condition)):
            tmp = []
            for value in each_and:
                # [valid, invalid]
                counts = [0,0]
                for item in re.sub('[^0-9a-zA-Z_.]+', ' ', value).split():
                    if re.search('^\w+\.\w+$', item):
                        x, y = item.split('.')
                        if x == self.legalize_name(x) and y == self.legalize_name(y):
                            if x.lower() not in tables:
                                counts[1] += 1
                            else:
                                counts[0] += 1
                                for k in self.data:
                                    if k.lower() == x:
                                        if not y.lower() in [i.lower() for i in self.data[k].keys()]:
                                            raise ResultDBError("``{}`` is invalid query: cannot find column ``{}`` in table ``{}``".\
                                                                format(value, y, k))
                if counts[0] >= 1 and counts[1] == 0:
                    tmp.append(value)
            condition.append(tmp)
        return "WHERE " + ' OR '.join(['(' + ' AND '.join(["({})".format(y) for y in x]) + ')' for x in condition])

    def population_table(self, table):
        # FIXME
        return table

    def get_queries(self):
        return self.queries

    def get_data(self):
        return self.data

if __name__ == '__main__':
    import sys
    q = Query_Processor(sys.argv[1], [sys.argv[2]], [sys.argv[3]])
    print(q.queries)
