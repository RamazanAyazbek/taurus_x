
def add_prev_hour_oi_features(df):
    if df.empty:
        return df

    df = df.copy()
    previous_values = []
    last_completed_hour_doi = None

    for _, row in df.iterrows():
        previous_values.append(last_completed_hour_doi)

        if row["dt"].minute == 0:
            last_completed_hour_doi = row["dOI"]

    df["doi_prev_hour"] = previous_values
    df["doi_impulse_change_60"] = df["dOI"] - df["doi_prev_hour"]
    return df
