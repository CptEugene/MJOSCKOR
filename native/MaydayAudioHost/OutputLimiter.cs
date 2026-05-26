namespace MaydayAudioHost;

internal sealed class OutputLimiter
{
    private readonly double _threshold;
    private readonly double _release;
    private readonly double _softClipDrive;
    private readonly double _softClipNormalizer;
    private double _gain = 1.0;

    public OutputLimiter(double threshold = 0.82, double release = 0.004, double softClipDrive = 1.25)
    {
        _threshold = Math.Clamp(threshold, 0.1, 0.99);
        _release = Math.Clamp(release, 0.0001, 1.0);
        _softClipDrive = Math.Max(0.1, softClipDrive);
        _softClipNormalizer = Math.Tanh(_softClipDrive);
    }

    public void Reset()
    {
        _gain = 1.0;
    }

    public float[] Process(float[] samples)
    {
        if (samples.Length == 0)
        {
            return samples;
        }

        var output = new float[samples.Length];
        var gain = _gain;
        for (int index = 0; index < samples.Length; index++)
        {
            var sample = samples[index];
            var absolute = Math.Abs(sample);
            double targetGain = 1.0;
            if (absolute > _threshold && absolute > 1.0e-9)
            {
                targetGain = _threshold / absolute;
            }

            if (targetGain < gain)
            {
                gain = targetGain;
            }
            else
            {
                gain += (1.0 - gain) * _release;
                gain = Math.Min(1.0, gain);
            }

            var limited = sample * gain;
            if (Math.Abs(limited) > _threshold)
            {
                var scaled = limited / _threshold;
                limited = (Math.Tanh(scaled * _softClipDrive) / _softClipNormalizer) * _threshold;
            }

            output[index] = (float)Math.Clamp(limited, -1.0, 1.0);
        }

        _gain = gain;
        return output;
    }
}
