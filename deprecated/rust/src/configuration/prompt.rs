use super::*;
use std::collections::{BTreeMap, BTreeSet};

pub(crate) fn valid_variable(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn placeholders(text: &str) -> Result<Vec<(usize, usize, String)>> {
    let mut found = Vec::new();
    let mut offset = 0;
    while let Some(start) = text[offset..].find("{{") {
        let start = offset + start;
        let end = text[start + 2..]
            .find("}}")
            .map(|end| start + 2 + end)
            .ok_or_else(|| Error::invalid("Unclosed prompt placeholder; use {{variable}}"))?;
        let variable = text[start + 2..end].trim();
        if !valid_variable(variable) {
            return Err(Error::invalid(format!(
                "Invalid prompt variable {variable:?}"
            )));
        }
        found.push((start, end + 2, variable.to_string()));
        offset = end + 2;
    }
    Ok(found)
}

pub(crate) fn validate(prompt: &Prompt) -> Result<()> {
    if prompt.text.trim().is_empty() {
        return Err(Error::invalid(format!(
            "Prompt {} must not be empty",
            prompt.id
        )));
    }
    let declared: BTreeSet<_> = prompt.variables.iter().cloned().collect();
    if declared.len() != prompt.variables.len() || declared.iter().any(|name| !valid_variable(name))
    {
        return Err(Error::invalid(format!(
            "Prompt {} has invalid or duplicate variable names",
            prompt.id
        )));
    }
    let actual: BTreeSet<_> = placeholders(&prompt.text)?
        .into_iter()
        .map(|(_, _, name)| name)
        .collect();
    if declared != actual {
        return Err(Error::invalid(format!(
            "Prompt {} variables must match its placeholders; found {actual:?}",
            prompt.id
        )));
    }
    Ok(())
}

pub(crate) fn render(prompt: &Prompt, values: &BTreeMap<String, String>) -> Result<String> {
    validate(prompt)?;
    let mut output = String::new();
    let mut offset = 0;
    for (start, end, variable) in placeholders(&prompt.text)? {
        output.push_str(&prompt.text[offset..start]);
        let value = values.get(&variable).ok_or_else(|| {
            Error::invalid(format!("Missing prompt input {variable} for {}", prompt.id))
        })?;
        output.push_str(value);
        offset = end;
    }
    output.push_str(&prompt.text[offset..]);
    // Input values are inserted once, never interpreted as further placeholders.
    Ok(output)
}
