# Configuration

The only configuration needed is to select the organization in which you want to work. To list the organizations available to your account, use:


```{.python notest}
from deeporigin import config

config.list_orgs()
```

You will be presented with a table similar to:

|	name| 	key |	autoApproveMaxAmount	| threshold|
| --- |  --- | --- | --- |
|	ACME Corp	| acme-corp	| 500 |	50.00 |
| Polaris Biotech |	polaris-bio | 	500 | 	50.00 |

Choose the organization you want, and set it using:

```{.python notest}
from deeporigin import config

config.set_org("polaris-bio")
```


## View configuration

To view the configuration for this package, run:


```{.python notest}
from deeporigin import config

config.get_value()

```
