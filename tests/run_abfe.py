import time
import uuid

from deeporigin.drug_discovery import BRD_DATA_DIR, Complex


def run_abfe():
    sim = Complex.from_dir(BRD_DATA_DIR)
    ligand = sim.ligands[6]

    print("Preparing system...")

    _ = sim.prepare(ligand=ligand, padding=1.0)
    print("System prepared", flush=True)

    sim.abfe.set_test_run(1)

    # set up output directory on ufa
    output_dir_path = f"/tests/{uuid.uuid4()}/"

    # get a quote for the job
    jobs = sim.abfe.run(ligands=[ligand], quote=True, output_dir_path=output_dir_path)
    job = jobs[0]

    assert job.status == "Quoted", (
        f"Expected job to be quoted, instead got {job.status}"
    )

    print("Job quoted", flush=True)

    print(job.id, flush=True)

    job.confirm()

    timeout_seconds = 20
    start_time = time.time()
    while job.status != "Running":
        elapsed_time = time.time() - start_time
        if elapsed_time >= timeout_seconds:
            raise TimeoutError(
                f"Job did not start running within {timeout_seconds} seconds. "
                f"Current status: {job.status}"
            )
        time.sleep(2)
        job.sync()

    # check that job is running
    assert job.status == "Running", (
        f"Expected job to be running, instead got {job.status}"
    )


if __name__ == "__main__":
    run_abfe()
