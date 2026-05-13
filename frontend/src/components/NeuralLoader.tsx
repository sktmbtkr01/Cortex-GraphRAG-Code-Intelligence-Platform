"use client";

import Loader from "@/components/ui/loader-15";

type NeuralLoaderProps = {
  status?: string;
  detail?: string;
};

export default function NeuralLoader({ status = "Loading Cortex", detail }: NeuralLoaderProps) {
  return (
    <section className="neural-loader-page">
      <div className="neural-loader-bg" aria-hidden="true" />
      <div className="neural-loader">
        <div className="matrix-loader-wrap" aria-hidden="true">
          <Loader />
        </div>
        <h1>{status}</h1>
        {detail && <p>{detail}</p>}
      </div>
    </section>
  );
}
