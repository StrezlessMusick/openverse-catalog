from ast import literal_eval
from pathlib import Path
from unittest import mock

import pytest
from airflow.models import TaskInstance
from airflow.providers.postgres.hooks.postgres import PostgresHook
from common.constants import IMAGE, POSTGRES_CONN_ID
from common.loader.reporting import RecordMetrics
from providers.provider_api_scripts import inaturalist


# TO DO #898: Most of the transformations for inaturalist are in SQL, and testing them
# effectively could mean looking more closely at the production data itself.
# For now, sample data included in the tests below covers the following weird cases:
#  - 3 of the photo records link to unclassified observations, so they have no title or
#    tags and we don't load them.
#  - 10 of the remaining photo ids appear on multiple records, load one per photo_id.
#  - One of the photos has a taxon without any ancestors in the source table.
#
# To get at data quality issues, it's worth loading bigger sample files to minio and
# running the dag in airflow locally:
#  - Use the aws cli to download these separate files observations.csv.gz,
#    observers.csv.gz, photos.csv.gz, and taxa.csv.gz from s3://inaturalist-open-data
#  - Consider whether you want to really test the full dataset, which may take a couple
#    of days to run locally, and will definitely take 10s of GB. If not, maybe use
#    tests/dags/providers/provider_api_scripts/resources/inaturalist/pull_sample_records.py
#    to pull a sample of records without breaking referential integrity.
#  - Putting your final zipped test files in /tests/s3-data/inaturalist-open-data
#    so that they will be synced over to minio.
#  - Run `just down -v` and then `just recreate` to make sure that the test data gets to
#    the test s3 instance. That process may take on the order of 15 minutes for the full
#    dataset. You'll know that it's done when the s3-load container in docker exits.
#  - Then, in airflow, trigger the dag possibly with configuration
#    {"sql_rm_source_data_after_ingesting": false} so that a) you don't have to
#    download catalog of life data over and over, and b) you can compare the results in
#    the image table to the raw data in the inaturalist schema.


INAT = inaturalist.INaturalistDataIngester()
PG = PostgresHook(POSTGRES_CONN_ID)
SQL_SCRIPT_DIR = (
    Path(__file__).parents[4]
    / "openverse_catalog/dags/providers/provider_csv_load_scripts/inaturalist"
)
RESOURCE_DIR = Path(__file__).parent / "resources/inaturalist"
# postgres always returns a list of tuples, which is not a valid json format
FULL_DB_RESPONSE = literal_eval((RESOURCE_DIR / "full_db_response.txt").read_text())
# in this case, it's a list containing a single tuple with a single value that is a
# valid json array of records for processing as if they came from a regular API.
JSON_RESPONSE = FULL_DB_RESPONSE[0][0]
RECORD0 = JSON_RESPONSE[0]


# Based on the small sample files in /tests/s3-data/inaturalist-open-data and on
# minio in the test environment
# Just checking raw record counts, assume that the contents load correctly as only
# taxa has any logic outside literally loading the table using postgres existing
# copy command.
@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("create_schema.sql", [("inaturalist",)]),
        ("photos.sql", [(37,)]),
        ("observations.sql", [(32,)]),
        ("taxa.sql", [(183,)]),
        ("observers.sql", [(23,)]),
    ],
)
def test_load_data(file_name, expected):
    sql_string = (SQL_SCRIPT_DIR / file_name).read_text()
    actual = PG.get_records(sql_string)
    assert actual == expected


@pytest.mark.parametrize("value", [None, {"offset_num": 0}])
def test_get_next_query_params(value):
    with pytest.raises(
        NotImplementedError,
        match="Instead we use get_batches to dynamically create subtasks.",
    ):
        INAT.get_next_query_params(value)


@pytest.mark.parametrize("value", [None, {}])
def test_get_batch_data_returns_none(value):
    with pytest.raises(
        NotImplementedError, match="TSV files from AWS S3 processed in postgres."
    ):
        INAT.get_batch_data(value)


def test_get_response_json():
    with pytest.raises(
        NotImplementedError, match="TSV files from AWS S3 processed in postgres."
    ):
        INAT.get_response_json({"offset_num": 0})


def test_get_batch_data_full_response():
    with pytest.raises(
        NotImplementedError, match="TSV files from AWS S3 processed in postgres."
    ):
        INAT.get_batch_data(JSON_RESPONSE)


@pytest.mark.parametrize("field", ["license_url", "foreign_identifier"])
def test_get_record_data_missing_necessarly_fields(field):
    with pytest.raises(
        NotImplementedError, match="TSV files from AWS S3 processed in postgres."
    ):
        INAT.get_record_data(RECORD0)


def test_get_record_data_full_response():
    with pytest.raises(
        NotImplementedError, match="TSV files from AWS S3 processed in postgres."
    ):
        INAT.get_record_data(RECORD0)


def test_get_media_type():
    expected = "image"
    actual = INAT.get_media_type({"some test": "data"})
    assert actual == expected


@pytest.mark.parametrize(
    "all_results, expected",
    [
        (None, None),
        (
            [
                {
                    "loaded": 0,
                    "max_id_loaded": None,
                    "missing_columns": 0,
                    "foreign_id_dup": 0,
                    "upserted": 0,
                    "duration": 0.07186045899288729,
                },
                {
                    "loaded": 1,
                    "max_id_loaded": "10314159",
                    "missing_columns": 0,
                    "foreign_id_dup": 0,
                    "upserted": 1,
                    "duration": 0.0823216249991674,
                },
            ],
            {IMAGE: RecordMetrics(1, 0, 0, 0)},
        ),
    ],
)
def test_consolidate_load_statistics(all_results, expected):
    ti_mock = mock.MagicMock(spec=TaskInstance)
    actual = INAT.consolidate_load_statistics(all_results, ti_mock)
    assert actual == expected


@pytest.mark.parametrize(
    "batch_length, max_id, expected",
    [
        pytest.param(10, [(22,)], [[(0, 9)], [(10, 19)], [(20, 29)]], id="happy_path"),
        pytest.param(10, [(2,)], [[(0, 9)]], id="bigger_batch_than_id"),
        pytest.param(10, [(None,)], None, id="no_data"),
    ],
)
def test_get_batches(batch_length, max_id, expected):
    with mock.patch.object(PostgresHook, "get_records", return_value=max_id) as pg_mock:
        actual = INAT.get_batches(batch_length, pg_mock)
        assert actual == expected
