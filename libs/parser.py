import pdfreader
from pdfreader import PDFDocument, SimplePDFViewer
from pdfreader.viewer import PageDoesNotExist
from datetime import datetime, timedelta
import logging
import decimal
import csv


decimal.getcontext().rounding = decimal.ROUND_HALF_UP

from libs import (
    REVOLUT_DATE_FORMAT,
    REVOLUT_ACTIVITY_TYPES,
    REVOLUT_CASH_ACTIVITY_TYPES,
    REVOLUT_ACTIVITIES_PAGES_INDICATORS,
    TRADING212_ACTIVITY_TYPES
)

logger = logging.getLogger("parser")


class ActivitiesNotFound(Exception):
    pass


def get_activity_range(page_strings):
    begin_index = None
    end_index = None

    for index, page_string in enumerate(page_strings):
        if page_string == "ACTIVITY":
            begin_index = index
            continue

        if page_string == "SWEEP ACTIVITY":
            end_index = index
            break

    if begin_index is None:
        raise ActivitiesNotFound()

    if end_index is None:
        end_index = len(page_strings)

    logger.debug(f"Found begin index: [{begin_index}] and end index: [{end_index}]")
    return begin_index + 1, end_index


def extract_symbol_description(begin_index, page_strings):
    symbol_description = ""
    symbol = ""
    end_index = begin_index
    for page_string in page_strings[begin_index:]:
        try:
            decimal.Decimal(clean_number(page_string))
            break
        except decimal.InvalidOperation:
            symbol_description += page_string
        end_index += 1

    symbol = symbol_description[0 : symbol_description.index("-") - 1]
    return end_index, symbol, symbol_description


def clean_number(number_string):
    return number_string.replace("(", "").replace(")", "").replace(",", "")


def extract_activity(begin_index, page_strings, num_fields):
    end_index, symbol, symbol_description = extract_symbol_description(begin_index + 4, page_strings)

    activity = {
        "trade_date": datetime.strptime(page_strings[begin_index], REVOLUT_DATE_FORMAT),
        "settle_date": datetime.strptime(page_strings[begin_index + 1], REVOLUT_DATE_FORMAT),
        "currency": page_strings[begin_index + 2],
        "activity_type": page_strings[begin_index + 3],
        "symbol_description": symbol_description,
    }

    if num_fields == 8:
        activity["symbol"] = symbol
        activity["quantity"] = decimal.Decimal(page_strings[end_index])
        activity["price"] = decimal.Decimal(page_strings[end_index + 1])
        activity["amount"] = page_strings[end_index + 2]
    elif num_fields == 6:
        activity["amount"] = page_strings[end_index]

    activity["amount"] = decimal.Decimal(clean_number(activity["amount"]))

    return activity


def extract_activities_from_pdf(viewer):
    activities = []

    while True:
        viewer.render()
        page_strings = viewer.canvas.strings

        logger.debug(f"Parsing page [{viewer.current_page_number}]")

        if page_strings:
            logger.debug(f"First string on the page: [{page_strings[0]}]")

            if page_strings[0] in REVOLUT_ACTIVITIES_PAGES_INDICATORS:
                try:
                    begin_index, end_index = get_activity_range(page_strings)
                    page_strings = page_strings[begin_index:end_index]
                    for index, page_string in enumerate(page_strings):
                        if page_string in REVOLUT_ACTIVITY_TYPES:
                            activity = extract_activity(index - 3, page_strings, 8)
                        elif page_string in REVOLUT_CASH_ACTIVITY_TYPES:
                            activity = extract_activity(index - 3, page_strings, 6)
                        else:
                            continue

                        activities.append(activity)
                except ActivitiesNotFound:
                    pass

        try:
            viewer.next()
        except PageDoesNotExist:
            break

    return activities


def extract_activities_from_csv(reader):
    activities = []

    for index, row in enumerate(reader):
        if index < 1:
            continue

        if not row:
            continue

        if row[0] in TRADING212_ACTIVITY_TYPES:
            activity = {
                "trade_date": datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S'),
                "settle_date": '-',
                "currency": row[7],
                "activity_type": REVOLUT_ACTIVITY_TYPES[TRADING212_ACTIVITY_TYPES.index(row[0])],
                "symbol_description": row[4] + " " + row[2],
                "symbol": row[3],
                "quantity": decimal.Decimal(row[5]),
                "price": decimal.Decimal(row[6]),
                "amount": decimal.Decimal(clean_number(row[10]))
            }

            activities.append(activity)

    return activities


def find_place_position(statements, date):
    pos = 0
    for statement in statements:
        if statement["trade_date"] > date:
            break

        pos += 1

    return pos


def parse_statements(statement_files):
    statements = []

    for statement_file in statement_files:
        logger.debug(f"Processing statement file[{statement_file}]")

        activities = []

        if statement_file.endswith('.pdf'):
            with open(statement_file, "rb") as fd:
                viewer = SimplePDFViewer(fd)
                activities = extract_activities_from_pdf(viewer)
        elif statement_file.endswith('.csv'):
            with open(statement_file, "r") as fd:
                viewer = csv.reader(fd, delimiter=",")
                activities = extract_activities_from_csv(viewer)

        if not activities:
            continue

        statements.append(activities)

    statements = sorted(statements, key=lambda k: k[0]["trade_date"])
    return [activity for activities in statements for activity in activities]
