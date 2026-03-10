import marimo

__generated_with = "0.20.4"
app = marimo.App(width="medium")


@app.cell
def _():
    from deeporigin.platform.client import DeepOriginClient

    client = DeepOriginClient()
    return (client,)


@app.cell
def _(client):
    response = client.entities.search_ligands(limit=1)
    return (response,)


@app.cell
def _(response):
    response
    return


@app.cell
def _(client):
    client.results.get()
    return


@app.cell
def _(functions):
    functions[0].keys()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
