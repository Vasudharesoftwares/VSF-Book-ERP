import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { alerts } from "../utils/alerts";

const API = "http://127.0.0.1:8000/api/v1";

export default function CustomFieldsForm({
  tenant,
  moduleKey,
  entityId,
  onValuesChange,
  onFieldsLoaded,
  showSave = true
}) {
  const [fields, setFields] = useState([]);
  const [values, setValues] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [products, setProducts] = useState([]);

  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Code": tenant
  };

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const response = await fetch(
          `${API}/custom-fields?module_key=${encodeURIComponent(moduleKey)}`,
          { headers }
        );
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not load fields.");

        const activeFields = (data.fields || []).filter(field => field.is_active);
        let savedValues = {};

        if (entityId !== undefined && entityId !== null) {
          const valueResponse = await fetch(
            `${API}/custom-field-values/${moduleKey}/${entityId}`,
            { headers }
          );
          const valueData = await valueResponse.json();
          if (!valueResponse.ok) {
            throw new Error(valueData.detail || "Could not load saved values.");
          }
          savedValues = valueData.values || {};
        }

        let productRows = [];
        if (activeFields.some(field => field.field_type === "product")) {
          const productResponse = await fetch(`${API}/products?limit=500`, { headers });
          const productData = await productResponse.json();
          if (!productResponse.ok) throw new Error(productData.detail || "Could not load products.");
          productRows = productData.products || [];
        }

        if (!cancelled) {
          setFields(activeFields);
          setValues(savedValues);
          setProducts(productRows);
          onFieldsLoaded?.(activeFields);
          onValuesChange?.(savedValues);
        }
      } catch (error) {
        if (!cancelled) alerts.error(error);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [tenant, moduleKey, entityId]);

  function update(field, value) {
    setValues(previous => {
      const next = { ...previous, [field.field_key]: value };
      onValuesChange?.(next);
      return next;
    });
  }

  async function save() {
    if (entityId === undefined || entityId === null) {
      return alerts.error(new Error("Save the main record before saving its custom fields."));
    }

    setSaving(true);
    try {
      const response = await fetch(
        `${API}/custom-field-values/${moduleKey}/${entityId}`,
        {
          method: "PUT",
          headers,
          body: JSON.stringify({ values })
        }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not save custom fields.");
      await alerts.success("Custom fields saved");
    } catch (error) {
      await alerts.error(error);
    } finally {
      setSaving(false);
    }
  }

  function renderField(field) {
    const value = values[field.field_key] ?? "";
    const common = {
      id: `custom-${field.id}`,
      required: Boolean(field.is_required),
      value: field.field_type === "checkbox" ? undefined : value,
      onChange: event => update(
        field,
        field.field_type === "checkbox" ? event.target.checked : event.target.value
      )
    };

    switch (field.field_type) {
      case "product":
        return (
          <select
            id={`custom-${field.id}`}
            required={Boolean(field.is_required)}
            value={value}
            onChange={event => update(field, event.target.value)}
          >
            <option value="">Select a product</option>
            {products.map(product => (
              <option key={product.id} value={String(product.id)}>
                {product.name} {product.sku ? `(${product.sku})` : ""}
              </option>
            ))}
          </select>
        );

      case "stock_quantity":
        return (
          <input
            {...common}
            type="number"
            step="any"
            placeholder="Enter quantity"
          />
        );

      case "adjustment_reason":
        return (
          <input
            {...common}
            type="text"
            placeholder="e.g. Opening stock or Purchase received"
          />
        );

      case "long_text":
        return <textarea {...common} rows="3" />;
      case "number":
        return <input {...common} type="number" step="1" />;
      case "decimal":
        return <input {...common} type="number" step="any" />;
      case "date":
        return <input {...common} type="date" />;
      case "email":
        return <input {...common} type="email" />;
      case "phone":
        return <input {...common} type="tel" />;
      case "dropdown":
        return (
          <select {...common}>
            <option value="">Select an option</option>
            {(field.options || []).map(option =>
              <option key={option} value={option}>{option}</option>
            )}
          </select>
        );
      case "multi_select":
        return (
          <select
            multiple
            value={Array.isArray(value) ? value : []}
            required={Boolean(field.is_required)}
            onChange={event => update(
              field,
              Array.from(event.target.selectedOptions, option => option.value)
            )}
          >
            {(field.options || []).map(option =>
              <option key={option} value={option}>{option}</option>
            )}
          </select>
        );
      case "checkbox":
        return (
          <input
            id={`custom-${field.id}`}
            type="checkbox"
            checked={Boolean(value)}
            onChange={event => update(field, event.target.checked)}
          />
        );
      default:
        return <input {...common} type="text" />;
    }
  }

  if (loading) return <p>Loading custom fields...</p>;
  if (!fields.length) return null;

  return (
    <section className="data-panel custom-fields-form">
      <h3>Additional Information</h3>
      <div className="form-grid">
        {fields.map(field => (
          <label key={field.id} htmlFor={`custom-${field.id}`}>
            {field.label}{field.is_required ? " *" : ""}
            {renderField(field)}
          </label>
        ))}
      </div>
      {showSave && entityId !== undefined && entityId !== null && (
        <button type="button" disabled={saving} onClick={save}>
          <Save size={16} /> {saving ? "Saving..." : "Save additional information"}
        </button>
      )}
    </section>
  );
}
