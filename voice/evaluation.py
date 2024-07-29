"""Word-level edit distance; normalization never repairs transcription mistakes."""
import re


def words(text):
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())
    if len(tokens) > 500:
        raise ValueError("evaluation text exceeds 500 words")
    return tokens


def word_error_rate(reference, hypothesis):
    expected, observed = words(reference), words(hypothesis)
    rows, columns = len(expected), len(observed)
    distance = [[0] * (columns + 1) for _ in range(rows + 1)]
    for row in range(rows + 1):
        distance[row][0] = row
    for column in range(columns + 1):
        distance[0][column] = column
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            distance[row][column] = min(
                distance[row - 1][column] + 1,
                distance[row][column - 1] + 1,
                distance[row - 1][column - 1]
                + (expected[row - 1] != observed[column - 1]),
            )
    substitutions = deletions = insertions = 0
    row, column = rows, columns
    while row or column:
        if (
            row
            and column
            and distance[row][column]
            == distance[row - 1][column - 1]
            + (expected[row - 1] != observed[column - 1])
        ):
            substitutions += expected[row - 1] != observed[column - 1]
            row, column = row - 1, column - 1
        elif row and distance[row][column] == distance[row - 1][column] + 1:
            deletions += 1
            row -= 1
        else:
            insertions += 1
            column -= 1
    errors = substitutions + deletions + insertions
    return dict(
        reference_words=rows,
        hypothesis_words=columns,
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        wer=errors / rows if rows else (None if errors else 0),
    )
