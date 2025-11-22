# Installation

## Recommended installation

!!! tip "Recommended installation"
    We recommend using the following script. A common source of errors in python packages is managing dependencies and conflicts with other packages, that is resolved using the method below. 

    You can of course install it yourself, using your package and environment manager of choice.  

This sections describes how to install the Deep Origin Python client on your computer using our recommendations. We recommend:

- Using the [uv :octicons-link-external-16:](https://docs.astral.sh/uv/) package and environment manager 
- Using [Jupyter Lab :octicons-link-external-16:](https://jupyter.org/) to run the Deep Origin Python client

=== "macOS/Linux"

    First, create a folder to contain your project. This can be any name (except deeporigin).

    ```bash
    mkdir do-client
    cd do-client
    ```

    Now use this one liner to install deeporigin using the [uv :octicons-link-external-16:](https://docs.astral.sh/uv/) package manager. 

    ```bash
    curl -LsSf https://client-docs.deeporigin.io/install.sh | sh
    ```

    Now start a Jupyter Lab instance that uses this environment, allowing you to use the `deeporigin` python client in it:


    ```bash
    # run jupyter using this environment
    uv run --with jupyter jupyter lab

    ```


=== "Windows"

    ```bash
    # make a folder for your project
    # this can be any name (except deeporigin)
    mkdir do-client
    cd do-client

    # install uv if needed
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

    # If uv tells you to add something to PATH,
    # you may need to do that first
    uv init

    # we use the latest stable version of python
    uv python install 3.13

    # install deeporigin in the current environment
    uv add deeporigin

    # if you're using Deep Origin tools (like FEP), use:
    uv add deeporigin --extra tools

    # also install as a uv tool to run from the command line
    uv tool install deeporigin

    # run jupyter using this environment
    uv run --with jupyter jupyter lab
    ```
### Upgrading to a new version

If you followed the recommended installation steps, you can upgrade to the latest version of the Deep Origin Python client by running:

```bash
uv add --upgrade deeporigin
```

in your project root. 



## OS and python support

`deeporigin` is [tested](https://github.com/deeporiginbio/deeporigin-client/actions/workflows/main.yml) against the following versions of Python on Ubuntu Linux and Windows:

| Python | macOS | Windows | Ubuntu |
| -- | -- | -- | -- | 
| 3.10| | ✅ | ✅ |
| 3.11| | ✅ | ✅ |
| 3.12| | ✅ | ✅ |
| 3.13 | ✅ | ✅ | ✅ |


